import sys
from faster_whisper import WhisperModel
model = WhisperModel("base", device="cpu", compute_type="int8")
segments, info = model.transcribe(sys.argv[1], vad_filter=True)
for s in segments:
    print(f"[{s.start:.1f}s -> {s.end:.1f}s] {s.text}")
