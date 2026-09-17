#!/usr/bin/env python3
"""
generate_intros.py — the batch job that fills the intro cache.

WHY THIS FILE EXISTS
--------------------
This is the slow half of the project, deliberately separated from the fast
half. It loads a 2 GB speech model, talks to a language model, and writes
WAV files. None of that can happen while music is playing on a Pi without
the music stalling.

Run it when you add music. Leave it overnight. Then never think about it
again until the next time.

USAGE
    python generate_intros.py                 # everything not yet cached
    python generate_intros.py --playlist "70s AT40"
    python generate_intros.py --limit 10      # try a few first
    python generate_intros.py --redo          # regenerate even if cached
    python generate_intros.py --dry-run       # write text only, no speech

The --dry-run flag is worth knowing about. It generates the intro TEXT for
every track without loading XTTS at all, so you can read what Casey is going
to say — and delete the bad ones — before spending hours synthesising them.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time

import requests

import config
import library

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("generate")


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def generate_text(track):
    """
    Ask the local language model for two sentences in Casey's voice.

    A note on what this model is doing: it has no database of music facts.
    It is predicting plausible continuations of the prompt, which means it
    will sometimes state things about an artist that are simply not true.

    On a personal radio station that is mostly charming, and the few-shot
    examples in your Modelfile do a lot of work keeping the style right. But
    it is worth knowing it is happening, and it is a good argument for
    reading manifest.json before you let a batch air.
    """
    album_hint = f" from the album {track.album}" if track.album else ""
    year_hint  = f" (released {track.year})" if track.year else ""

    prompt = (
        f"You are Casey Kasem on American Top 40. "
        f"Introduce '{track.title}' by {track.artist}{album_hint}{year_hint}. "
        f"Tell one brief interesting story or fact about the artist or song. "
        f"Build up naturally so the song title comes at the very end. "
        f"Two short sentences, under {config.MAX_INTRO_CHARS} characters total. "
        f"Warm, classic Casey style. No chart positions or countdown numbers."
    )

    resp = requests.post(
        config.OLLAMA_URL,
        json={"model": config.OLLAMA_MODEL, "prompt": prompt, "stream": False},
        timeout=config.OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    text = resp.json()["response"].strip()

    # Models like to wrap speech in quotation marks. XTTS reads them as a
    # pause, which sounds like a stumble at the start of a line.
    text = text.strip('"').strip("'").strip()

    # Hard truncation as a last resort. XTTS silently cuts off past ~250
    # characters, and a sentence that ends mid-word sounds broken. Better to
    # end at the last complete sentence we have room for.
    if len(text) > config.MAX_INTRO_CHARS:
        cut = text[:config.MAX_INTRO_CHARS]
        for stop in (". ", "! ", "? "):
            idx = cut.rfind(stop)
            if idx > 40:
                cut = cut[:idx + 1]
                break
        text = cut.strip()

    return text


# ---------------------------------------------------------------------------
# Speech
# ---------------------------------------------------------------------------

def apply_radio_filter(src, dst):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-i", src, "-filter_complex",
         config.RADIO_FILTER, "-map", "[out]", "-ar", "24000", dst, "-y"],
        check=True, capture_output=True,
    )


def synthesize(tts, text, out_path):
    """
    Speak the text in Casey's cloned voice, then push it through the radio
    filter.

    The filter is doing more work than it looks. XTTS output has small
    artefacts around pitch transitions that read as "synthetic" on clean
    playback. Bandpassing to a transmitter's frequency range removes most of
    the range where those artefacts live, and the noise floor masks the rest.
    You are not hiding a flaw so much as putting the voice in the acoustic
    context it is imitating.
    """
    raw = out_path.replace(".wav", "_raw.wav")
    tts.tts_to_file(
        text=text,
        speaker_wav=config.VOICE_REFS,
        language="en",
        speed=config.VOICE_SPEED,
        temperature=config.VOICE_TEMP,
        file_path=raw,
    )
    apply_radio_filter(raw, out_path)
    os.remove(raw)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--playlist", help="only tracks in this playlist")
    ap.add_argument("--limit", type=int, help="stop after N tracks")
    ap.add_argument("--redo", action="store_true", help="regenerate cached entries")
    ap.add_argument("--dry-run", action="store_true", help="text only, no speech")
    args = ap.parse_args()

    os.makedirs(config.CACHE_DIR, exist_ok=True)

    manifest = {}
    if os.path.exists(config.MANIFEST):
        with open(config.MANIFEST) as f:
            manifest = json.load(f)

    root = library.find_music()
    if not root:
        log.error("no music folder at %s", config.MUSIC_DIR)
        sys.exit(1)

    tracks = library.scan(root)

    if args.playlist:
        pls = {p.name.lower(): p for p in library.load_playlists()}
        pl = pls.get(args.playlist.lower())
        if not pl:
            log.error("no playlist named %r. Available: %s",
                      args.playlist, ", ".join(p.name for p in pls.values()))
            sys.exit(1)
        tracks = pl.filter(tracks)
        log.info("playlist %s: %d tracks", pl.name, len(tracks))

    todo = tracks if args.redo else [t for t in tracks if t.key not in manifest]
    if args.limit:
        todo = todo[:args.limit]

    log.info("%d to generate, %d already cached", len(todo), len(tracks) - len(todo))
    if not todo:
        return

    # Load XTTS only if we are actually going to speak. It takes a while and
    # about 2 GB of RAM, and --dry-run has no use for it.
    tts = None
    if not args.dry_run:
        log.info("loading XTTS (this takes a moment)...")
        from TTS.api import TTS
        tts = TTS(config.XTTS_MODEL)

    started = time.time()
    failures = 0

    for i, track in enumerate(todo, 1):
        t0 = time.time()
        try:
            text = generate_text(track)

            if args.dry_run:
                log.info("[%d/%d] %s\n         %s", i, len(todo), track, text)
                manifest[track.key] = {
                    "artist": track.artist, "title": track.title,
                    "text": text, "wav": None,
                }
            else:
                wav_name = f"{track.key}.wav"
                synthesize(tts, text, os.path.join(config.CACHE_DIR, wav_name))
                manifest[track.key] = {
                    "artist": track.artist, "title": track.title,
                    "text": text, "wav": wav_name,
                }
                elapsed = time.time() - t0
                rate = (time.time() - started) / i
                left = rate * (len(todo) - i)
                log.info("[%d/%d] %5.1fs  %-46s  eta %s",
                         i, len(todo), elapsed, str(track)[:46],
                         time.strftime("%H:%M:%S", time.gmtime(left)))

        except Exception as e:
            failures += 1
            log.warning("[%d/%d] FAILED %s: %s", i, len(todo), track, e)

        # Save after every single track. A four-hour batch that loses
        # everything because the power blipped at hour three is the kind of
        # mistake you only make once. Writing a small JSON file 200 times
        # costs nothing; losing 200 generations costs an evening.
        with open(config.MANIFEST, "w") as f:
            json.dump(manifest, f, indent=2)

    total = time.time() - started
    log.info("\ndone in %s — %d cached, %d failed",
             time.strftime("%H:%M:%S", time.gmtime(total)),
             len(manifest), failures)


if __name__ == "__main__":
    main()
