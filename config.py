"""
config.py — every tunable value in the project, in one place.

WHY THIS FILE EXISTS
--------------------
Configuration scattered through a codebase is the single most common reason
a project becomes painful to change. If the GPIO pin for the NEXT button is
written directly inside the function that reads it, then rewiring your panel
means hunting through code. If it lives here, rewiring means editing one line.

The rule of thumb: if you might change it without changing the logic, it is
configuration, not code.
"""

import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# __file__ is the path to THIS file. Deriving everything from it means the
# project works no matter where you put it — no hardcoded /home/pi/...
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))

CACHE_DIR = os.path.join(BASE_DIR, "cache")     # generated intro WAVs
LOG_DIR   = os.path.join(BASE_DIR, "logs")
TMP_DIR   = os.path.join(BASE_DIR, "tmp")
MANIFEST  = os.path.join(CACHE_DIR, "manifest.json")
PLAYLISTS = os.path.join(BASE_DIR, "playlists.json")

# Where your music lives. Everything under here is scanned recursively, so
# organise it however you like — by artist, by decade, or one flat folder.
#
# On the SD card is simplest. If your library outgrows the card, point this
# at a mounted USB drive instead; nothing else in the code changes.
MUSIC_DIR = os.path.expanduser("~/music")

# File types worth trying to read. Anything else is skipped silently.
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".aiff", ".aif",
              ".ogg", ".opus", ".wma"}

# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------

# The tuned reference set. Order does not matter; the count and the specific
# clips do. These were chosen by ear — do not add to them casually.
VOICE_REFS = [os.path.join(BASE_DIR, f) for f in [
    "casey_ref.wav",  "casey_ref2.wav", "casey_ref3.wav", "casey_ref4.wav",
    "casey_ref5.wav", "casey_ref6.wav", "casey_ref7.wav",
]]

XTTS_MODEL  = "tts_models/multilingual/multi-dataset/xtts_v2"
VOICE_SPEED = 1.1     # 1.0 sounded sluggish; 1.15 was slightly rushed
VOICE_TEMP  = 0.7     # lower = steadier pitch, less expressive

# The ffmpeg filter chain that makes synthetic speech sound like it came
# through a transmitter. Bandpass narrows it to a telephone-ish range,
# the compressor evens out the level, and a little pink noise fills the
# silences the way a real radio's noise floor does.
RADIO_FILTER = (
    "[0:a]highpass=f=300,lowpass=f=3400,"
    "acompressor=threshold=-18dB:ratio=4:attack=5:release=50[voice];"
    "anoisesrc=color=pink:amplitude=0.015:duration=60[noise];"
    "[voice][noise]amix=inputs=2:duration=first:weights=1 0.3[out]"
)

# ---------------------------------------------------------------------------
# Language model
# ---------------------------------------------------------------------------

OLLAMA_URL     = "http://localhost:11434/api/generate"
OLLAMA_MODEL   = "casey"
OLLAMA_TIMEOUT = 120          # generous: a Pi under load is slow

# 250 characters is XTTS's practical limit before it truncates mid-sentence.
# We ask for less than that so there is headroom.
MAX_INTRO_CHARS = 200

# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

SAMPLE_RATE = 44100
CHANNELS    = 2

# Frames handed to the sound card per callback. Bigger = more slack before
# an underrun (a dropout), at the cost of latency. 2048 frames at 44.1 kHz
# is about 46 ms of buffer. For music playback that latency is invisible;
# for a synthesiser you would want far less. A Pi that is also running an
# LLM needs the slack.
BLOCK_SIZE = 2048

# ---------------------------------------------------------------------------
# GPIO pins — BCM numbering
# ---------------------------------------------------------------------------
# Two numbering schemes exist for the 40-pin header and mixing them up is
# the classic beginner mistake. BCM numbers are the chip's own GPIO numbers.
# BOARD numbers are physical positions 1-40. gpiozero uses BCM.
# GPIO 17 and physical pin 11 are the same hole described two ways.

PIN_SOURCE  = 16   # SPDT toggle: closed = Bluetooth, open = library
PIN_CASEY   = 20   # SPDT toggle: closed = narration on

PIN_PREV    = 17   # momentary
PIN_PAUSE   = 27   # momentary
PIN_NEXT    = 22   # momentary

PIN_ENC_A   = 5    # rotary encoder channel A
PIN_ENC_B   = 6    # rotary encoder channel B
PIN_ENC_SW  = 13   # encoder push-to-select

# Mechanical contacts do not close cleanly. They bounce for a few
# milliseconds, which a computer reads as several presses. Ignoring
# further transitions for this long after the first one fixes it.
BOUNCE_BUTTON = 0.08   # seconds
BOUNCE_TOGGLE = 0.05

# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------

# Pressing PREV within this many seconds of a track starting goes to the
# previous track. Later than that, it restarts the current one. This is
# how every media player you have ever used behaves.
PREV_RESTART_THRESHOLD = 4.0

HISTORY_LENGTH = 50

# Bluetooth playback is handed to an external process. We do not decode it
# ourselves; we just start and stop the bridge.
BLUEALSA_CMD = ["bluealsa-aplay", "--profile-a2dp"]

# ---------------------------------------------------------------------------
# Input backend
# ---------------------------------------------------------------------------
# "auto"     — use GPIO if the library imports, otherwise keyboard
# "gpio"     — force hardware
# "keyboard" — force keyboard, even on a Pi with wiring attached
CONTROLS_BACKEND = os.environ.get("CASEY_CONTROLS", "auto")
