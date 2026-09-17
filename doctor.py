#!/usr/bin/env python3
"""
doctor.py — check whether this machine can actually run the radio.

WHY THIS FILE EXISTS
--------------------
A fresh clone of this repository is not a working radio. It needs system
packages, Python dependencies, an audio device, a language model, voice
reference clips that are deliberately not distributed here, and some music.

Without this script, a missing piece surfaces as an exception several layers
deep — "ModuleNotFoundError: No module named 'sounddevice'" tells you almost
nothing about which of the six install steps you skipped.

So every dependency gets checked in one place, in dependency order, with a
concrete fix printed next to each failure. Running it costs two seconds and
replaces a debugging session.

This pattern is worth reusing. Any project with a nontrivial setup benefits
from a single command that answers "is this machine ready?" — it is the
difference between a project that only the author can run and one that
someone else can pick up.

    python doctor.py
"""

import importlib
import os
import shutil
import subprocess
import sys

# ANSI colours. Disabled when output is piped, so logs stay readable.
_tty = sys.stdout.isatty()
GREEN = "\033[32m" if _tty else ""
AMBER = "\033[33m" if _tty else ""
RED   = "\033[31m" if _tty else ""
DIM   = "\033[2m"  if _tty else ""
OFF   = "\033[0m"  if _tty else ""

results = []


def report(name, status, detail="", fix=""):
    """status: 'ok' | 'warn' | 'fail'"""
    results.append(status)
    mark = {"ok": f"{GREEN}  OK  {OFF}",
            "warn": f"{AMBER} WARN {OFF}",
            "fail": f"{RED} FAIL {OFF}"}[status]
    print(f"[{mark}] {name}")
    if detail:
        print(f"         {DIM}{detail}{OFF}")
    if fix and status != "ok":
        print(f"         {DIM}fix: {fix}{OFF}")


# ---------------------------------------------------------------------------

def check_python():
    v = sys.version_info
    if v < (3, 9):
        report("Python version", "fail", f"{v.major}.{v.minor}",
               "Python 3.9 or newer is required")
    else:
        report("Python version", "ok", f"{v.major}.{v.minor}.{v.micro}")


def check_venv():
    active = sys.prefix != sys.base_prefix
    if active:
        report("Virtual environment", "ok", sys.prefix)
    else:
        report("Virtual environment", "warn", "not active",
               "source venv/bin/activate")


def check_packages():
    # (import name, pip name, required?)
    pkgs = [
        ("numpy",       "numpy",       True),
        ("sounddevice", "sounddevice", True),
        ("soundfile",   "soundfile",   True),
        ("mutagen",     "mutagen",     True),
        ("requests",    "requests",    True),
        ("TTS",         "coqui-tts",   False),   # only needed to generate
        ("gpiozero",    "gpiozero",    False),   # only on a Pi
    ]
    for mod, pip_name, required in pkgs:
        try:
            importlib.import_module(mod)
            report(f"python: {pip_name}", "ok")
        except Exception as e:
            note = "required for playback" if required else "optional"
            report(f"python: {pip_name}",
                   "fail" if required else "warn",
                   f"{note} — {type(e).__name__}",
                   f"pip install {pip_name}")


def check_ffmpeg():
    if shutil.which("ffmpeg"):
        try:
            out = subprocess.run(["ffmpeg", "-version"],
                                 capture_output=True, text=True, timeout=10)
            ver = out.stdout.split("\n")[0].replace("ffmpeg version ", "")[:40]
            report("ffmpeg", "ok", ver)
        except Exception:
            report("ffmpeg", "ok", "present")
    else:
        report("ffmpeg", "fail", "not on PATH",
               "sudo apt install ffmpeg   (macOS: brew install ffmpeg)")


def check_audio_output():
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        outputs = [d for d in devices if d["max_output_channels"] > 0]
        if not outputs:
            report("Audio output", "fail", "no output devices found",
                   "check `aplay -l` and ~/.asoundrc")
            return
        try:
            default_idx = sd.default.device[1]
            name = devices[default_idx]["name"]
        except Exception:
            name = outputs[0]["name"]
        report("Audio output", "ok",
               f"default: {name}  ({len(outputs)} device(s))")
    except Exception as e:
        report("Audio output", "fail", str(e)[:60],
               "sudo apt install libportaudio2 portaudio19-dev")


def check_voice_refs():
    try:
        import config
    except Exception as e:
        report("Voice references", "fail", f"cannot import config: {e}")
        return

    present = [p for p in config.VOICE_REFS if os.path.exists(p)]
    missing = len(config.VOICE_REFS) - len(present)

    if not present:
        report("Voice references", "warn",
               f"0 of {len(config.VOICE_REFS)} present",
               "Not distributed with this repository — supply your own "
               "10-20s mono 24kHz WAV clips. Playback of cached intros still "
               "works without them; only generation needs them.")
    elif missing:
        report("Voice references", "warn",
               f"{len(present)} of {len(config.VOICE_REFS)} present",
               "generation will fail until all are in place")
    else:
        report("Voice references", "ok", f"{len(present)} clips")


def check_music():
    try:
        import config, library
    except Exception as e:
        report("Music library", "fail", f"import failed: {e}")
        return

    root = library.find_music()
    if not root:
        report("Music library", "fail", f"{config.MUSIC_DIR} not found",
               f"mkdir -p {config.MUSIC_DIR} and copy audio in, "
               f"or edit MUSIC_DIR in config.py")
        return

    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        count += sum(1 for f in filenames
                     if not f.startswith(".")
                     and os.path.splitext(f)[1].lower() in config.AUDIO_EXTS)

    if count == 0:
        report("Music library", "fail", f"{root} contains no audio files",
               "copy some music in")
    else:
        report("Music library", "ok", f"{count} files under {root}")


def check_ollama():
    try:
        import requests, config
    except Exception:
        report("Ollama", "warn", "requests not installed, cannot check")
        return

    base = config.OLLAMA_URL.rsplit("/api/", 1)[0]
    try:
        r = requests.get(f"{base}/api/tags", timeout=4)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        report("Ollama", "warn", "server not responding",
               "curl -fsSL https://ollama.com/install.sh | sh  "
               "&& sudo systemctl start ollama")
        return

    want = config.OLLAMA_MODEL
    if any(m.split(":")[0] == want or m == want for m in models):
        report("Ollama", "ok", f"model '{want}' available")
    else:
        have = ", ".join(models[:4]) if models else "none"
        report("Ollama", "warn", f"model '{want}' not found (have: {have})",
               "cp Modelfile.example Modelfile && "
               f"ollama create {want} -f Modelfile")


def check_cache():
    try:
        import config, json
    except Exception:
        return

    if not os.path.exists(config.MANIFEST):
        report("Intro cache", "warn", "empty",
               "python generate_intros.py --dry-run --limit 10   "
               "(review text first, then drop --dry-run)")
        return

    try:
        manifest = json.load(open(config.MANIFEST))
    except Exception as e:
        report("Intro cache", "fail", f"manifest unreadable: {e}")
        return

    have_wav = sum(
        1 for e in manifest.values()
        if e.get("wav") and os.path.exists(os.path.join(config.CACHE_DIR, e["wav"]))
    )
    report("Intro cache", "ok",
           f"{have_wav} synthesised, {len(manifest)} entries")


def check_controls():
    backend = os.environ.get("CASEY_CONTROLS", "auto")
    try:
        import gpiozero  # noqa: F401
        from gpiozero import Device
        try:
            Device.pin_factory  # triggers backend selection
            report("Controls", "ok", f"GPIO available (CASEY_CONTROLS={backend})")
        except Exception:
            report("Controls", "warn", "gpiozero installed but no GPIO present",
                   "expected off a Pi — keyboard backend will be used")
    except ImportError:
        report("Controls", "warn", "gpiozero not installed",
               "expected off a Pi — keyboard backend will be used")


# ---------------------------------------------------------------------------

def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    print()
    print("Casey Radio — environment check")
    print("=" * 52)

    for section, checks in [
        ("Runtime",      [check_python, check_venv]),
        ("Dependencies", [check_packages, check_ffmpeg]),
        ("Hardware",     [check_audio_output, check_controls]),
        ("Content",      [check_voice_refs, check_music]),
        ("Generation",   [check_ollama, check_cache]),
    ]:
        print(f"\n{DIM}{section}{OFF}")
        for fn in checks:
            try:
                fn()
            except Exception as e:
                report(fn.__name__, "fail", f"check itself errored: {e}")

    fails = results.count("fail")
    warns = results.count("warn")

    print("\n" + "=" * 52)
    if fails:
        print(f"{RED}{fails} blocking issue(s){OFF}"
              + (f", {warns} warning(s)" if warns else ""))
        print("Fix the failures above, then run this again.")
        sys.exit(1)
    elif warns:
        print(f"{AMBER}{warns} warning(s){OFF} — the radio will run, "
              f"but some features are unavailable.")
        sys.exit(0)
    else:
        print(f"{GREEN}All checks passed.{OFF}  python radio.py")
        sys.exit(0)


if __name__ == "__main__":
    main()
