#!/usr/bin/env bash
# POC 31 — Gemini transcription of sung vocals + per-song WhisperX
# baseline + comparison vs ground truth. Outputs go under
# outputs/${TRACK_NAME}/ so cross-song runs do not overwrite each other.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

cd "$REPO_ROOT"

TRACK_NAME="${1:-my-little-blackbird}"
VOCALS="pocs/07-whisperx/stems/htdemucs_6s/${TRACK_NAME}/vocals.wav"
LYRICS="music/${TRACK_NAME}.txt"
OUT_DIR="$HERE/outputs/${TRACK_NAME}"
mkdir -p "$OUT_DIR"

if [[ ! -f "$VOCALS" ]]; then
  echo "ERROR: vocals stem missing at $VOCALS"
  echo "Run pocs/07-whisperx/scripts/run.sh ${TRACK_NAME} first to produce it."
  exit 1
fi
if [[ ! -f "$LYRICS" ]]; then
  echo "ERROR: ground-truth lyrics missing at $LYRICS"
  exit 1
fi

echo "=== Variant Gemini — gemini-2.5-pro ($TRACK_NAME) ==="
/usr/bin/time -l -o "$OUT_DIR/time-gemini.txt" \
  uv run python "$HERE/scripts/transcribe_gemini.py" \
    "$VOCALS" \
    "$OUT_DIR/gemini.json" \
    2>&1 | tee "$OUT_DIR/stdout-gemini.log"

uv run python - <<PY
import json, pathlib
d = json.loads(pathlib.Path("$OUT_DIR/gemini.json").read_text())
text = d.get("segments", [{}])[0].get("text", "")
pathlib.Path("$OUT_DIR/gemini.txt").write_text(text)
print(f"Wrote $OUT_DIR/gemini.txt — {len(text.split())} words")
PY

echo ""
echo "=== Variant W — WhisperX baseline ($TRACK_NAME) ==="
/usr/bin/time -l -o "$OUT_DIR/time-whisperx.txt" \
  uv run python "$REPO_ROOT/pocs/30-whisper-timestamped/scripts/transcribe_whisperx_noprompt.py" \
    "$VOCALS" \
    "$OUT_DIR/whisperx-noprompt.json" \
    2>&1 | tee "$OUT_DIR/stdout-whisperx.log"

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

echo ""
echo "=== Comparison: Gemini vs WhisperX vs ground truth ($TRACK_NAME) ==="
uv run python "$REPO_ROOT/pocs/30-whisper-timestamped/scripts/compare.py" \
  "$LYRICS" \
  "$OUT_DIR/gemini.json" \
  "$OUT_DIR/whisperx-noprompt.json" \
  "$OUT_DIR/comparison.md"

echo ""
echo "=== done: $TRACK_NAME ==="
ls -lh "$OUT_DIR"
