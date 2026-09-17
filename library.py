"""
library.py — what music exists, how it is grouped, and what Casey says about it.

WHY THIS FILE EXISTS
--------------------
Three jobs that all answer questions about content rather than about sound:

  - Where is the music and what is it?     (scanning)
  - Which subset am I playing?             (playlists)
  - Do I have an intro for this track?      (cache)

Keeping them together and away from playback means you can test all of it
with no speakers attached, which is exactly what you want when a bug could
be in either half.
"""

import glob
import hashlib
import json
import logging
import os
import random
import re

from mutagen import File as MutagenFile

import config

log = logging.getLogger("casey.library")


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------

class Track:
    """
    One song. A small class rather than a dict because attribute access
    (track.title) fails loudly on a typo, while dict access (track["titel"])
    fails at the worst possible moment with a KeyError deep in a callback.
    """

    __slots__ = ("path", "title", "artist", "album", "year", "duration")

    def __init__(self, path, title, artist, album, year, duration):
        self.path     = path
        self.title    = title
        self.artist   = artist
        self.album    = album
        self.year     = year
        self.duration = duration

    def __repr__(self):
        return f"{self.artist} — {self.title}"

    @property
    def key(self):
        """
        Stable identifier for caching.

        Deliberately derived from artist and title rather than file path,
        because an iPod stores music under scrambled names like F04/AGID.m4a
        and reshuffles them when you re-sync. Hash the thing that does not
        move.

        Lowercased so that "Fleetwood Mac" and "fleetwood mac" resolve to
        the same cached intro.
        """
        raw = f"{self.artist}|{self.title}".lower().encode("utf-8")
        return hashlib.sha1(raw).hexdigest()[:16]


def find_music():
    """
    Return the music directory, or None if it is missing or empty.

    Simpler than it used to be. When the music lived on an iPod we had to
    hunt for a mount point that could appear under several different paths
    and change name between plug-ins. Files on the SD card just sit where
    you put them.
    """
    root = config.MUSIC_DIR
    if not os.path.isdir(root):
        return None
    return root


def _from_filename(path):
    """
    Guess artist and title from the filename when tags are missing.

    This is newly worth doing. An iPod stored everything under scrambled
    names like F04/AGID.m4a, so the filename told you nothing. Files you
    copied yourself are usually named something like

        Fleetwood Mac - Dreams.mp3
        03 - Dreams.mp3

    which is enough to work with. Untagged files would otherwise be dropped
    entirely, and on a hand-assembled library that can be a lot of music.
    """
    stem = os.path.splitext(os.path.basename(path))[0]

    # Strip a leading track number: "03 - ", "03. ", "03 "
    stem = re.sub(r"^\s*\d{1,3}\s*[-._)]?\s+", "", stem)

    for sep in (" - ", " – ", " — ", "-"):
        if sep in stem:
            left, right = stem.split(sep, 1)
            left, right = left.strip(), right.strip()
            if left and right:
                return left, right
    return None, stem.strip()


def scan(root):
    """
    Walk the music directory and read tags from every file.

    os.walk recurses into every subfolder, so your organisation scheme is up
    to you — Artist/Album/Track, one flat folder, or a mess. It all works.

    This opens every file to read its metadata, so on a few thousand tracks
    it takes a moment. We do it once at startup and hold the result in
    memory; scanning is cheap compared to how often we need the answer.
    """
    tracks = []
    skipped = 0

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip hidden directories (.Trash, .Spotlight-V100 and friends)
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]

        for name in filenames:
            # macOS writes "._Something.mp3" resource-fork files onto
            # non-Mac filesystems. They look like audio and are not.
            if name.startswith("."):
                continue
            if os.path.splitext(name)[1].lower() not in config.AUDIO_EXTS:
                continue

            path = os.path.join(dirpath, name)
            try:
                tags = MutagenFile(path, easy=True)

                title  = artist = None
                album  = ""
                year   = None
                duration = 0.0

                if tags:
                    title  = (tags.get("title")  or [None])[0]
                    artist = (tags.get("artist") or [None])[0]
                    album  = str((tags.get("album") or [""])[0])

                    # Dates arrive in every imaginable format: "1977",
                    # "1977-05-12", "05/1977". The first four digits are
                    # the year in all of them.
                    raw_year = str((tags.get("date") or [""])[0])[:4]
                    if raw_year.isdigit():
                        year = int(raw_year)

                    if hasattr(tags, "info"):
                        duration = float(tags.info.length)

                # Fall back to the filename for whatever the tags lacked.
                if not title or not artist:
                    guess_artist, guess_title = _from_filename(path)
                    artist = artist or guess_artist
                    title  = title  or guess_title

                if not title:
                    skipped += 1
                    continue

                tracks.append(Track(path, str(title),
                                    str(artist or "Unknown Artist"),
                                    album, year, duration))
            except Exception as e:
                skipped += 1
                log.debug("skipped %s: %s", name, e)

    log.info("scanned %d playable tracks (%d skipped)", len(tracks), skipped)
    return tracks


# ---------------------------------------------------------------------------
# Playlists
# ---------------------------------------------------------------------------

DEFAULT_PLAYLISTS = {
    "playlists": [
        {"name": "ALL TRACKS", "match": {}},
    ]
}


class Playlist:
    """A named filter over the library."""

    def __init__(self, name, match):
        self.name  = name
        self.match = match or {}

    def contains(self, track):
        m = self.match
        if not m:
            return True     # empty rules means everything

        if "artists" in m:
            # Substring match so "Hall" catches "Hall & Oates" and
            # "Daryl Hall & John Oates" without you having to get the
            # ampersand exactly right.
            hay = track.artist.lower()
            if not any(a.lower() in hay for a in m["artists"]):
                return False

        if "year_range" in m:
            lo, hi = m["year_range"]
            if track.year is None or not (lo <= track.year <= hi):
                return False

        if "albums" in m:
            hay = track.album.lower()
            if not any(a.lower() in hay for a in m["albums"]):
                return False

        return True

    def filter(self, tracks):
        return [t for t in tracks if self.contains(t)]


def load_playlists():
    if not os.path.exists(config.PLAYLISTS):
        log.info("no playlists.json — writing a default")
        with open(config.PLAYLISTS, "w") as f:
            json.dump(DEFAULT_PLAYLISTS, f, indent=2)
        data = DEFAULT_PLAYLISTS
    else:
        with open(config.PLAYLISTS) as f:
            data = json.load(f)

    return [Playlist(p["name"], p.get("match")) for p in data["playlists"]]


# ---------------------------------------------------------------------------
# Intro cache
# ---------------------------------------------------------------------------

class IntroCache:
    """
    Pre-generated speech, looked up by track.

    THE POINT OF THIS CLASS
    -----------------------
    On your MacBook, XTTS generated a 12-second intro in about 30 seconds.
    On a Pi 5 the same work takes minutes. Generating during playback would
    mean the radio regularly stalls waiting for the next line.

    So we move the work out of the listening path entirely. Intros are
    generated once by generate_intros.py — a batch job you run overnight —
    and playback becomes a file read.

    This is one of the most broadly useful patterns in engineering: when
    production is slower than consumption, precompute. Compilers do it,
    databases do it with indexes, game engines do it with baked lighting.
    The trade is always the same — you spend storage and lose the ability to
    react to inputs you did not know in advance, and you gain predictable
    latency.

    Here the trade is obviously worth it. The set of songs is known ahead of
    time, and a WAV file costs a few megabytes.
    """

    def __init__(self):
        self.manifest = {}
        self.reload()

    def reload(self):
        if os.path.exists(config.MANIFEST):
            with open(config.MANIFEST) as f:
                self.manifest = json.load(f)
            log.info("intro cache: %d entries", len(self.manifest))
        else:
            self.manifest = {}
            log.info("intro cache empty — run generate_intros.py")

    def has(self, track):
        return track.key in self.manifest

    def get(self, track):
        """
        Return (samples, samplerate, text) or None.

        Note that the WAV is read from disk at the moment it is needed, not
        held in memory. A few hundred intros would be a lot of RAM, and the
        read takes a few milliseconds — well inside the gap between a song
        ending and the next one starting.
        """
        entry = self.manifest.get(track.key)
        if not entry:
            return None

        path = os.path.join(config.CACHE_DIR, entry["wav"])
        if not os.path.exists(path):
            log.warning("manifest lists %s but file is missing", entry["wav"])
            return None

        from audio import load_wav
        samples, sr = load_wav(path)
        return samples, sr, entry.get("text", "")

    def coverage(self, tracks):
        """How much of a track list has intros. Useful before a long run."""
        have = sum(1 for t in tracks if self.has(t))
        return have, len(tracks)


# ---------------------------------------------------------------------------
# Shuffle
# ---------------------------------------------------------------------------

class Shuffler:
    """
    Endless shuffle that plays everything once before repeating.

    Picking at random each time (random.choice) feels wrong to listeners:
    with 20 tracks you will hear a repeat within the first few songs about
    half the time, and people read that as the shuffle being broken. Drawing
    without replacement from a shuffled pool, then reshuffling when it runs
    dry, is what every music player actually does.

    A small illustration of a general point: the mathematically correct
    answer and the one that feels correct are often different, and for
    anything a person experiences directly, feel wins.
    """

    def __init__(self, tracks):
        self.set_tracks(tracks)

    def set_tracks(self, tracks):
        self._tracks = list(tracks)
        self._pool   = []

    def next(self):
        if not self._tracks:
            return None
        if not self._pool:
            self._pool = list(self._tracks)
            random.shuffle(self._pool)
            log.info("reshuffled %d tracks", len(self._pool))
        return self._pool.pop()
