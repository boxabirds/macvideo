#!/usr/bin/env bash
#
# POC 3 follow-up — same I2V test on the dev pipeline.
# Confirms PR #24's VAE fix applies to dev as well as distilled.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$HERE/outputs"
IN_DIR="$HERE/inputs"
mkdir -p "$OUT_DIR"

REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

REF="$IN_DIR/reference.png"
if [[ ! -f "$REF" ]]; then
  echo "ERROR: $REF missing. Run scripts/run.sh first."
  exit 1
fi

PROMPT="slow pull back from the wreck, wide establishing shot emerging, overcast light, 16mm grain, no figures"

/usr/bin/time -l -o "$OUT_DIR/time-dev.txt" \
  uv run mlx_video.ltx_2.generate \
    --prompt "$PROMPT" \
    --seed 42 \
    --pipeline dev \
    --model-repo prince-canuma/LTX-2.3-dev \
    --text-encoder-repo mlx-community/gemma-3-12b-it-bf16 \
    --width 512 --height 320 \
    --num-frames 73 --fps 24 \
    --image "$REF" \
    --image-strength 1.0 \
    --image-frame-idx 0 \
    --output-path "$OUT_DIR/i2v-dev.mp4" \
  2>&1 | tee "$OUT_DIR/stdout-dev.log"

ffmpeg -y -hide_banner -loglevel error -i "$OUT_DIR/i2v-dev.mp4" -vframes 1 "$OUT_DIR/frame_0-dev.png"

echo ""
echo "=== done ==="
ls -lh "$OUT_DIR"/*dev*
