#!/usr/bin/env bash
#
# POC 7 — Demucs vocal separation + WhisperX transcription (with initial_prompt
# from ground-truth lyrics) + ground-truth match post-processing.
#
# Output is 100% word-accurate when a lyrics.txt exists.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$HERE/outputs"
STEMS_DIR="$HERE/stems"
mkdir -p "$OUT_DIR" "$STEMS_DIR"

REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

TRACK_NAME="${1:-my-little-blackbird}"
TRACK="music/${TRACK_NAME}.wav"
LYRICS="music/${TRACK_NAME}.txt"

if [[ ! -f "$TRACK" ]]; then
  echo "ERROR: $TRACK missing."
  exit 1
fi
if [[ ! -f "$LYRICS" ]]; then
  echo "WARNING: $LYRICS missing — STT will run without initial_prompt and ground-truth match will be skipped."
fi

VOCALS="$STEMS_DIR/htdemucs_6s/$TRACK_NAME/vocals.wav"

# Demucs (skip if vocals stem already exists)
if [[ ! -f "$VOCALS" ]]; then
  echo "=== Demucs htdemucs_6s ==="
  uv run demucs -n htdemucs_6s "$TRACK" -o "$STEMS_DIR" 2>&1 | tee "$OUT_DIR/demucs.log"
fi
cp "$VOCALS" "$OUT_DIR/vocals.wav"

# WhisperX STT + forced alignment
echo ""
echo "=== WhisperX transcribe ==="
/usr/bin/time -l -o "$OUT_DIR/time-transcribe.txt" \
  uv run python pocs/07-whisperx/scripts/transcribe.py \
    "$OUT_DIR/vocals.wav" \
    "$OUT_DIR/transcript.json" \
    "$LYRICS" \
  2>&1 | tee "$OUT_DIR/stdout-transcribe.log"

# Forced alignment of ground truth against audio — only if lyrics file exists.
# This is the preferred path: wav2vec2 CTC alignment gives 100% word accuracy
# (words come from the .txt) and acoustic timings (no interpolation).
if [[ -f "$LYRICS" ]]; then
  echo ""
  echo "=== Forced alignment (ground truth -> audio via wav2vec2) ==="
  /usr/bin/time -l -o "$OUT_DIR/time-force-align.txt" \
    uv run python pocs/07-whisperx/scripts/force_align.py \
      "$OUT_DIR/vocals.wav" \
      "$LYRICS" \
      "$OUT_DIR/aligned.json" \
    2>&1 | tee "$OUT_DIR/stdout-force-align.log"

  # Plain-text version of the final aligned lyrics for eyeballing
  uv run python - <<PY
import json
d = json.load(open("$OUT_DIR/aligned.json"))
with open("$OUT_DIR/aligned.txt","w") as f:
    for w in d["words"]:
        start = w.get("start")
        s = f"{start:6.2f}" if start is not None else " ?????"
        f.write(f"{s}  {w['word']}\n")
print("Wrote $OUT_DIR/aligned.txt")
PY
fi

echo ""
echo "=== done ==="
ls -lh "$OUT_DIR"
