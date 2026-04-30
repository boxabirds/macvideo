#!/usr/bin/env bash
# POC 30 — drive both transcription variants on my-little-blackbird vocals
# and produce a side-by-side comparison vs ground truth.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
OUT_DIR="$HERE/outputs"
mkdir -p "$OUT_DIR"

cd "$REPO_ROOT"

TRACK_NAME="${1:-my-little-blackbird}"
VOCALS="pocs/07-whisperx/stems/htdemucs_6s/${TRACK_NAME}/vocals.wav"
LYRICS="music/${TRACK_NAME}.txt"

if [[ ! -f "$VOCALS" ]]; then
  echo "ERROR: vocals stem missing at $VOCALS"
  echo "Run pocs/07-whisperx/scripts/run.sh ${TRACK_NAME} first to produce it."
  exit 1
fi
if [[ ! -f "$LYRICS" ]]; then
  echo "ERROR: ground-truth lyrics missing at $LYRICS"
  exit 1
fi

# Variant M — music2vid recipe
echo "=== Variant M — whisper-timestamped ==="
/usr/bin/time -l -o "$OUT_DIR/time-m.txt" \
  uv run python "$HERE/scripts/transcribe_timestamped.py" \
    "$VOCALS" \
    "$OUT_DIR/timestamped.json" \
    2>&1 | tee "$OUT_DIR/stdout-m.log"

# Plain text version for eyeballing
uv run python - <<PY
import json, pathlib
d = json.loads(pathlib.Path("$OUT_DIR/timestamped.json").read_text())
lines = []
for seg in d.get("segments", []):
    for w in seg.get("words", []):
        token = (w.get("text") or w.get("word") or "").strip()
        start = w.get("start")
        s = f"{start:6.2f}" if start is not None else " ?????"
        if token:
            lines.append(f"{s}  {token}")
pathlib.Path("$OUT_DIR/timestamped.txt").write_text("\n".join(lines))
print(f"Wrote $OUT_DIR/timestamped.txt — {len(lines)} words")
PY

# Variant W — WhisperX no initial_prompt
echo ""
echo "=== Variant W — WhisperX (no initial_prompt) ==="
/usr/bin/time -l -o "$OUT_DIR/time-w.txt" \
  uv run python "$HERE/scripts/transcribe_whisperx_noprompt.py" \
    "$VOCALS" \
    "$OUT_DIR/whisperx-noprompt.json" \
    2>&1 | tee "$OUT_DIR/stdout-w.log"

uv run python - <<PY
import json, pathlib
d = json.loads(pathlib.Path("$OUT_DIR/whisperx-noprompt.json").read_text())
lines = []
for seg in d.get("segments", []):
    text = seg.get("text", "").strip()
    start = seg.get("start")
    s = f"{start:6.2f}" if start is not None else " ?????"
    if text:
        lines.append(f"{s}  {text}")
pathlib.Path("$OUT_DIR/whisperx-noprompt.txt").write_text("\n".join(lines))
print(f"Wrote $OUT_DIR/whisperx-noprompt.txt — {len(lines)} segments")
PY

# Compare
echo ""
echo "=== Comparison ==="
uv run python "$HERE/scripts/compare.py" \
  "$LYRICS" \
  "$OUT_DIR/timestamped.json" \
  "$OUT_DIR/whisperx-noprompt.json" \
  "$OUT_DIR/comparison.md"

echo ""
echo "=== done ==="
ls -lh "$OUT_DIR"
