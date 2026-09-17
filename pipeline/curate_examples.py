import json, re, random

blocks = [json.loads(l) for l in open("casey_corpus.jsonl")]

good = []
for b in blocks:
    words = b["text"].split()
    n = len(words)
    if 8 <= n <= 45:
        first = words[0].lower().strip(",.")
        if first in ("and","but","or","so","then","after","until","because","with","while"):
            continue
        good.append(b)

chart_pos = [b for b in good if re.search(r"number \d+", b["text"], re.I)]
trivia = [b for b in good if re.search(r"19\d{2}|debut|career|album|wrote|written|first (hit|song|record)", b["text"], re.I)]
transitions = [b for b in good if re.search(r"stick around|coming up|countdown|right back", b["text"], re.I)]

print(f"good={len(good)} chart_pos={len(chart_pos)} trivia={len(trivia)} transitions={len(transitions)}")

random.seed(42)
picks = (random.sample(chart_pos, min(6, len(chart_pos))) +
         random.sample(trivia, min(5, len(trivia))) +
         random.sample(transitions, min(4, len(transitions))))

for e in picks:
    print(f"[{e['episode']:02d}] {e['text']}")
