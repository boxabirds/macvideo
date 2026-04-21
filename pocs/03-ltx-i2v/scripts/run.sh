#!/usr/bin/env bash
#
# POC 3 — LTX-2.3 image-to-video from a static still.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$HERE/outputs"
IN_DIR="$HERE/inputs"
mkdir -p "$OUT_DIR" "$IN_DIR"

REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

# Copy the POC 2 a_no_audio first frame as the input reference
REF_SRC="pocs/02-ltx-audio-cond/outputs/frame_a_no_audio.png"
REF="$IN_DIR/reference.png"
if [[ ! -f "$REF" ]]; then
  if [[ ! -f "$REF_SRC" ]]; then
    echo "ERROR: $REF_SRC missing. Run POC 2 first (it extracts the frames)."
    exit 1
  fi
  cp "$REF_SRC" "$REF"
fi
cp "$REF" "$OUT_DIR/input.png"

PROMPT="slow pull back from the wreck, wide establishing shot emerging, overcast light, 16mm grain, no figures"

/usr/bin/time -l -o "$OUT_DIR/time.txt" \
  uv run mlx_video.ltx_2.generate \
    --prompt "$PROMPT" \
    --seed 42 \
    --pipeline distilled \
    --model-repo prince-canuma/LTX-2.3-distilled \
    --text-encoder-repo mlx-community/gemma-3-12b-it-bf16 \
    --width 512 --height 320 \
    --num-frames 73 --fps 24 \
    --image "$REF" \
    --image-strength 1.0 \
    --image-frame-idx 0 \
    --output-path "$OUT_DIR/i2v.mp4" \
  2>&1 | tee "$OUT_DIR/stdout.log"

# Extract frame 0 for direct comparison
ffmpeg -y -hide_banner -loglevel error -i "$OUT_DIR/i2v.mp4" -vframes 1 "$OUT_DIR/frame_0.png"

echo ""
echo "=== done ==="
ls -lh "$OUT_DIR"
echo ""
echo "Compare: open $OUT_DIR/input.png $OUT_DIR/frame_0.png $OUT_DIR/i2v.mp4"
