import json, re, os
from collections import Counter

CASEY_KW = re.compile(
    r"american top (forty|40)|casey kasem|countdown|\bchart\b|"
    r"this week|last week|weeks? ago|debut|\b19\d{2}\b|dedication|"
    r"request|hit record|hit single|stick around|coming up|"
    r"top forty|long distance|moving (up|down)|moves (up|down)|"
    r"on the chart|at number|to number|notches?|titled|"
    r"covering a song|written and performed by|performed by|"
    r"the latest from|chart debut|enjoyed.*hits|"
    r"this time by|rewrote the lyrics|reinvented the song|"
    r"character study|came up to me and said",
    re.IGNORECASE)
EXCLUDE_KW = re.compile(
    r"sirius|series xm|70'?s on 7|continue exploring|"
    r"discover more from your favorite",
    re.IGNORECASE)

def norm(t):
    t = t.lower().strip()
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t)

def has_internal_repeat(text):
    words = norm(text).split()
    if len(words) < 6:
        return False
    for n in (2, 3, 4):
        seen = set()
        for i in range(len(words) - n + 1):
            gram = tuple(words[i:i+n])
            if gram in seen:
                return True
            seen.add(gram)
    return False

stats = Counter()
for i in range(1, 19):
    p = f"transcripts/{i:02d}.json"
    if not os.path.exists(p):
        continue
    segs = json.load(open(p))
    norms = [norm(s["text"]) for s in segs]
    counts = Counter(norms)

    casey, uncertain, lyrics, excluded = [], [], [], []
    for s, n in zip(segs, norms):
        dur = s["end"] - s["start"]
        if EXCLUDE_KW.search(s["text"]):
            excluded.append(s)
            continue
        if CASEY_KW.search(s["text"]):
            casey.append(s)
            continue
        if counts[n] >= 2 and n:
            lyrics.append(s)
            continue
        if has_internal_repeat(s["text"]):
            lyrics.append(s)
            continue
        (uncertain if dur >= 5 else lyrics).append(s)

    json.dump(casey, open(f"filtered/{i:02d}_casey.json", "w"), indent=2)
    json.dump(uncertain, open(f"filtered/{i:02d}_uncertain.json", "w"), indent=2)
    stats["casey"] += len(casey)
    stats["uncertain"] += len(uncertain)
    stats["lyrics"] += len(lyrics)
    stats["excluded"] += len(excluded)
    print(f"{i:02d}: casey={len(casey)} uncertain={len(uncertain)} lyrics={len(lyrics)} excluded={len(excluded)}")

print("TOTALS:", dict(stats))
