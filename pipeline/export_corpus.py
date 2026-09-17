import json, os, random

MERGE_GAP = 2.0
all_blocks = []
for i in range(1, 19):
    p = f"filtered/{i:02d}_casey.json"
    if not os.path.exists(p):
        continue
    segs = sorted(json.load(open(p)), key=lambda s: s["start"])
    blocks = []
    for s in segs:
        if blocks and s["start"] - blocks[-1]["end"] <= MERGE_GAP:
            blocks[-1]["end"] = s["end"]
            blocks[-1]["text"] += " " + s["text"].strip()
        else:
            blocks.append({"start": s["start"], "end": s["end"], "text": s["text"].strip()})
    for b in blocks:
        b["episode"] = i
        all_blocks.append(b)

with open("casey_corpus.jsonl", "w") as f:
    for b in all_blocks:
        f.write(json.dumps(b) + "\n")

words = sum(len(b["text"].split()) for b in all_blocks)
print(f"Blocks: {len(all_blocks)}")
print(f"Total words: {words}")
print(f"Avg words/block: {words/len(all_blocks):.1f}")

print("\n=== SAMPLE BLOCKS ===")
random.seed(3)
for b in random.sample(all_blocks, 8):
    dur = b["end"] - b["start"]
    print(f"[{b['episode']:02d}] ({dur:.1f}s, {len(b['text'].split())}w) {b['text']}")
