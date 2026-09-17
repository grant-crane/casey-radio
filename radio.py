#!/usr/bin/env python3
"""
radio.py — the state machine that ties everything together. Run this.

WHY THIS FILE EXISTS
--------------------
Everything else in the project answers a narrow question. This file decides
what happens next.

The shape is a state machine: at any moment the radio is in exactly one
mode, each mode knows how to run itself, and the top-level loop just asks
"which mode should I be in?" and hands over control.

    ┌─────────────────────────────────┐
    │  SOURCE toggle == bluetooth?    │
    └───────┬─────────────────┬───────┘
            │ yes             │ no
            ▼                 ▼
      bluetooth mode     library mode
      (bridge runs,      (play one track,
       we just wait)      then return)

Writing it this way means adding a fourth mode later — an FM tuner, an aux
input, a sleep timer — is a new branch and a new method, not surgery on
tangled conditionals.

Note that library mode plays exactly ONE track and returns. It would be
natural to write it as a loop that plays forever, but then flipping the
SOURCE toggle could not take effect until that loop chose to exit. Returning
to the top after every track means the outer loop re-reads the switches
constantly, and the radio stays responsive to physical controls. Keeping
the top-level loop shallow is what makes the machine feel alive.
"""

import logging
import logging.handlers
import os
import subprocess
import threading
import time
from collections import deque

import config
import library
from audio import Player, decode
from controls import make_controls


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging():
    """
    Log to a rotating file AND to the terminal.

    Rotation matters on an appliance. A radio left running for a month would
    otherwise fill the SD card with a single enormous log file. maxBytes and
    backupCount bound it: at most 4 files of 2 MB each, oldest deleted.

    The timing lines below (GAP, INTRO, TRACK) exist so that things you
    perceive by ear become numbers you can inspect afterwards. "The
    transition feels laggy" cannot be debugged. "GAP seconds=0.847" can.
    Instrumenting subjective complaints into objective measurements is most
    of what makes a hard problem tractable.
    """
    os.makedirs(config.LOG_DIR, exist_ok=True)
    handlers = [
        logging.handlers.RotatingFileHandler(
            os.path.join(config.LOG_DIR, "casey.log"),
            maxBytes=2_000_000, backupCount=3),
        logging.StreamHandler(),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


log = logging.getLogger("casey.radio")


# ---------------------------------------------------------------------------
# The radio
# ---------------------------------------------------------------------------

class Radio:

    def __init__(self):
        self.controls  = make_controls()
        self.player    = Player()
        self.cache     = library.IntroCache()
        self.playlists = library.load_playlists()

        self.all_tracks   = []
        self.playlist_idx = 0
        self.pending_idx  = 0        # where the tuning knob currently points
        self.shuffler     = library.Shuffler([])
        self.history      = deque(maxlen=config.HISTORY_LENGTH)

        # Threading events as signals between the control thread and the
        # main loop. An Event is the right tool here: setting one is atomic,
        # checking it is cheap enough to do inside an audio callback, and it
        # carries no data that could go stale.
        self._quit = threading.Event()
        self._skip = threading.Event()
        self._back = threading.Event()

        self._track_started = 0.0
        self._prefetched    = None   # (Track, samples, samplerate)

        # Wire the abstract control events to real behaviour. The controls
        # object has no idea what any of this means.
        self.controls.on_next   = self._on_next
        self.controls.on_prev   = self._on_prev
        self.controls.on_pause  = self._on_pause
        self.controls.on_tune   = self._on_tune
        self.controls.on_select = self._on_select
        self.controls.on_quit   = self._quit.set

    # --- control handlers -------------------------------------------------
    # These run on the input thread, not the main loop. So they do the
    # minimum possible: set a flag and return. All the real work happens on
    # the main loop when it notices. Handlers that do heavy work on a
    # callback thread are a reliable source of race conditions.

    def _on_next(self):
        log.info("BUTTON next")
        self._skip.set()
        self.player.stop()

    def _on_prev(self):
        elapsed = time.time() - self._track_started
        if elapsed > config.PREV_RESTART_THRESHOLD:
            log.info("BUTTON prev (restart, %.1fs in)", elapsed)
        else:
            log.info("BUTTON prev (previous track)")
            self._back.set()
        self._skip.set()
        self.player.stop()

    def _on_pause(self):
        self.player.toggle_pause()
        log.info("BUTTON %s", "pause" if self.player.is_paused else "resume")

    def _on_tune(self, delta):
        n = len(self.playlists)
        self.pending_idx = (self.pending_idx + delta) % n
        log.info("TUNE -> %s", self.playlists[self.pending_idx].name)

    def _on_select(self):
        if self.pending_idx == self.playlist_idx:
            log.info("SELECT (unchanged)")
            return
        self.playlist_idx = self.pending_idx
        self._apply_playlist()
        self._skip.set()
        self.player.stop()

    # --- playlist ---------------------------------------------------------

    def _apply_playlist(self):
        pl = self.playlists[self.playlist_idx]
        tracks = pl.filter(self.all_tracks)
        self.shuffler.set_tracks(tracks)
        self._prefetched = None

        have, total = self.cache.coverage(tracks)
        log.info("PLAYLIST %s — %d tracks, %d/%d have intros",
                 pl.name, len(tracks), have, total)

        if not tracks:
            log.warning("playlist %s matched nothing", pl.name)

    # --- track sourcing ---------------------------------------------------

    def _next_track(self):
        if self._back.is_set():
            self._back.clear()
            if len(self.history) >= 2:
                self.history.pop()               # the one just played
                return self.history.pop()
        return self.shuffler.next()

    def _decode_track(self, track):
        """
        Get samples for a track, using the prefetched copy if it matches.

        Decoding a four-minute MP3 on a Pi takes a couple of seconds. Doing
        it while the previous song plays hides that entirely — the listener
        never waits, because the work happened during time that was already
        being spent.

        This is latency hiding, and it is the same idea as a CPU's branch
        predictor or a web page preloading the next image. You cannot make
        the work faster, so you move it somewhere nobody is watching.
        """
        if self._prefetched and self._prefetched[0] is track:
            _, samples, sr = self._prefetched
            self._prefetched = None
            return samples, sr

        t0 = time.time()
        samples, sr = decode(track.path)
        log.info("DECODE %.2fs %s", time.time() - t0, track)
        return samples, sr

    def _prefetch(self, track):
        if track is None:
            return

        def work():
            try:
                samples, sr = decode(track.path)
                self._prefetched = (track, samples, sr)
            except Exception as e:
                log.warning("prefetch failed for %s: %s", track, e)

        threading.Thread(target=work, daemon=True).start()

    # --- modes ------------------------------------------------------------

    def _bluetooth_mode(self):
        """
        Hand the sound card to BlueALSA and wait.

        We do not decode Bluetooth audio ourselves. bluealsa-aplay is a
        bridge that receives the A2DP stream from your phone and writes it
        to ALSA. Our job is only to make sure we are not holding the device
        while it runs — which is why the player is stopped first and why
        this method blocks instead of returning.
        """
        log.info("SOURCE bluetooth")
        self.player.stop()

        try:
            proc = subprocess.Popen(config.BLUEALSA_CMD,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            log.error("bluealsa-aplay not installed — "
                      "sudo apt install bluez-alsa-utils")
            while self.controls.source_is_bluetooth() and not self._quit.is_set():
                time.sleep(0.3)
            return

        try:
            while self.controls.source_is_bluetooth() and not self._quit.is_set():
                time.sleep(0.2)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            log.info("SOURCE library")

    def _library_mode(self):
        """Play one track — intro then song — and return."""
        track = self._next_track()
        if track is None:
            time.sleep(0.5)
            return

        self.history.append(track)
        self._skip.clear()

        # --- intro --------------------------------------------------------
        # casey_enabled() is read here, at the moment the decision is made,
        # rather than being cached at startup. That is what makes the toggle
        # work mid-playlist: flip it on during a song and the NEXT
        # transition narrates.
        if self.controls.casey_enabled():
            entry = self.cache.get(track)
            if entry:
                samples, sr, text = entry
                log.info("CASEY: %s", text)

                # And this closure is what makes flipping it OFF mid-sentence
                # stop him immediately. The audio callback evaluates it every
                # block, so the switch takes effect within ~46 ms.
                def stop_intro():
                    return self._skip.is_set() \
                        or not self.controls.casey_enabled() \
                        or self.controls.source_is_bluetooth()

                t0 = time.time()
                finished = self.player.play(samples, sr, should_stop=stop_intro)
                log.info("INTRO %.2fs %s", time.time() - t0,
                         "complete" if finished else "cut short")
            else:
                log.info("no cached intro for %s", track)

        if self._skip.is_set() or self.controls.source_is_bluetooth():
            return

        # --- song ---------------------------------------------------------
        try:
            samples, sr = self._decode_track(track)
        except Exception as e:
            log.error("cannot play %s: %s", track, e)
            return

        # Queue up the next decode before starting this song, so the work
        # happens during playback.
        upcoming = self.shuffler._pool[-1] if self.shuffler._pool else None
        self._prefetch(upcoming)

        gap = time.time()
        log.info("TRACK %s", track)
        self._track_started = time.time()
        log.info("GAP seconds=%.3f", self._track_started - gap)

        def stop_song():
            return self._skip.is_set() or self.controls.source_is_bluetooth()

        self.player.play(samples, sr, should_stop=stop_song)

    # --- main -------------------------------------------------------------

    def run(self):
        root = library.find_music()
        if not root:
            log.error("no music folder at %s — create it and copy music in",
                      config.MUSIC_DIR)
            return

        log.info("music: %s", root)
        self.all_tracks = library.scan(root)
        if not self.all_tracks:
            log.error("no readable tracks in %s", root)
            return

        self._apply_playlist()
        self.controls.start()

        log.info("=" * 46)
        log.info("  CASEY RADIO — on air")
        log.info("=" * 46)

        try:
            while not self._quit.is_set():
                if self.controls.source_is_bluetooth():
                    self._bluetooth_mode()
                else:
                    self._library_mode()
        except KeyboardInterrupt:
            log.info("interrupted")
        finally:
            # Release resources in the reverse order they were acquired.
            # The player goes first because it owns the sound card, and
            # nothing else can safely touch audio until it has let go.
            self.player.stop()
            self.controls.stop()
            log.info("Keep your feet on the ground, "
                     "and keep reaching for the stars.")


def main():
    setup_logging()
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    os.makedirs(config.TMP_DIR, exist_ok=True)
    Radio().run()


if __name__ == "__main__":
    main()
