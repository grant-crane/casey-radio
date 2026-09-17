"""
audio.py — decoding files and pushing samples to the sound card.

WHY THIS FILE EXISTS
--------------------
Exactly one part of the program is allowed to own the audio output device.
Every audio bug in this project so far came from two things trying to hold
it at once: sounddevice streaming Casey's voice while afplay started a song,
and the resulting fight produced skipping and distortion.

Concentrating all device access in one class makes that mistake structurally
hard to repeat. If you want sound, you go through Player. There is no second
path.

The same principle applies far beyond audio — serial ports, GPIO lines,
files opened for writing, network sockets. Give every exclusive resource
exactly one owner.
"""

import logging
import subprocess
import threading

import numpy as np
import sounddevice as sd

import config

log = logging.getLogger("casey.audio")


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

def decode(path, samplerate=None, channels=None):
    """
    Turn any audio file into a numpy array of float32 samples.

    We shell out to ffmpeg rather than using a Python decoder, for three
    reasons: it handles every format the iPod might hold (MP3, AAC in M4A,
    ALAC, WAV), it is written in heavily optimised C, and it is already a
    dependency because the radio filter uses it.

    The interesting part is the last argument, "-". That tells ffmpeg to
    write to standard output instead of a file, so the decoded audio comes
    back to us through a pipe with no temporary file touching the SD card.
    On a Pi that matters — SD cards are slow and have finite write cycles.

    "-f f32le" asks for raw 32-bit little-endian floats with no container
    or header, which is exactly numpy's native layout. So the conversion
    from ffmpeg's output to a usable array is a reinterpret, not a parse:

        np.frombuffer(raw, dtype=np.float32)

    That is a zero-copy view over the same bytes. Free.
    """
    samplerate = samplerate or config.SAMPLE_RATE
    channels   = channels   or config.CHANNELS

    cmd = [
        "ffmpeg", "-v", "error",
        "-i", path,
        "-f", "f32le",              # raw float32, no header
        "-acodec", "pcm_f32le",
        "-ar", str(samplerate),
        "-ac", str(channels),
        "-",                        # write to stdout
    ]

    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed on {path}: {proc.stderr.decode(errors='replace')[:300]}"
        )

    samples = np.frombuffer(proc.stdout, dtype=np.float32)
    if channels > 1:
        # One long stream of interleaved samples becomes an (N, channels)
        # array. -1 means "work out this dimension from the total length".
        samples = samples.reshape(-1, channels)

    return samples, samplerate


def load_wav(path):
    """Load an already-decoded WAV, e.g. a cached intro."""
    import soundfile as sf
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    return data, sr


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------

class Player:
    """
    Owns the output stream. Plays one buffer at a time, blocking until it
    finishes or is told to stop.

    ABOUT THE AUDIO CALLBACK
    ------------------------
    The `callback` function below is the most constrained piece of code in
    this project, and understanding why is worth more than the rest of the
    file.

    It does not run on your thread. The sound card driver runs it on a
    high-priority thread, on a hard schedule: every BLOCK_SIZE frames, it
    needs a new chunk of audio. At 44.1 kHz with 2048-frame blocks, that is
    every 46 milliseconds, forever, with no exceptions.

    If the callback has not returned by the time the card needs the next
    block, the card plays whatever was in the buffer — usually silence or a
    repeat — and you hear a click or a dropout. This is called an underrun,
    and it is not recoverable after the fact. You cannot apologise to a
    speaker cone.

    So inside a callback you must never:

        - read or write a file
        - allocate memory (numpy operations that create new arrays)
        - acquire a lock that another thread might hold
        - call print() or log
        - do anything of unbounded duration

    All of those can block for an unpredictable length of time. Reading from
    an array you already have in memory, and checking a boolean, are safe.

    This constraint is not specific to audio. It is the defining property of
    a real-time system: correctness depends not only on producing the right
    answer but on producing it before a deadline. A motor controller that
    computes a perfect correction 10 ms late has failed. The same discipline
    applies to interrupt handlers in embedded work.
    """

    def __init__(self):
        self._paused = threading.Event()
        self._stop   = threading.Event()
        self._lock   = threading.Lock()   # protects against overlapping play()
        self.position = 0.0               # seconds into current buffer
        self.duration = 0.0

    # --- control ---------------------------------------------------------

    def pause(self):
        self._paused.set()

    def resume(self):
        self._paused.clear()

    def toggle_pause(self):
        if self._paused.is_set():
            self.resume()
        else:
            self.pause()

    @property
    def is_paused(self):
        return self._paused.is_set()

    def stop(self):
        self._stop.set()

    # --- playback --------------------------------------------------------

    def play(self, samples, samplerate, should_stop=None):
        """
        Play a buffer. Blocks until it finishes or is interrupted.

        `should_stop` is a callable returning True when playback should end
        early. Passing a function rather than a flag lets the caller express
        conditions the Player knows nothing about — "stop if the Casey
        toggle went off" is one line at the call site and requires no change
        here.

        Returns True if the buffer played to the end, False if interrupted.
        """
        if samples.ndim == 1:
            samples = samples.reshape(-1, 1)

        total = len(samples)
        if total == 0:
            return True

        self._stop.clear()
        self._paused.clear()
        self.duration = total / samplerate

        done = threading.Event()
        pos  = [0]          # a list because the callback needs to mutate it

        def callback(outdata, frames, time_info, status):
            # `status` reports underruns. Checking it is cheap; logging from
            # here would not be, so we only set a flag the outer code reads.
            if self._stop.is_set() or (should_stop and should_stop()):
                raise sd.CallbackStop()

            if self._paused.is_set():
                # Output silence without advancing position. The stream keeps
                # running, so resuming is instant — no device reopen, no gap.
                outdata[:] = 0
                return

            remaining = total - pos[0]
            if remaining <= 0:
                raise sd.CallbackStop()

            n = min(frames, remaining)
            outdata[:n] = samples[pos[0]:pos[0] + n]
            if n < frames:
                outdata[n:] = 0        # pad the final partial block
            pos[0] += n

        # The `with` block opens the device and guarantees it is closed even
        # if an exception escapes. That guarantee is the whole reason the
        # "one owner" rule is enforceable.
        with self._lock:
            with sd.OutputStream(samplerate=samplerate,
                                 channels=samples.shape[1],
                                 dtype="float32",
                                 blocksize=config.BLOCK_SIZE,
                                 callback=callback,
                                 finished_callback=done.set):
                # Poll rather than waiting forever, so position stays current
                # for anything watching (the display, later).
                while not done.wait(timeout=0.1):
                    self.position = pos[0] / samplerate

        self.position = pos[0] / samplerate
        return pos[0] >= total
