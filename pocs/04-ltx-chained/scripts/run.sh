#!/usr/bin/env bash
#
# POC 4 — chained shots via last-frame conditioning.
# Reuses POC 3's clip A as the chain source.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$HERE/outputs"
IN_DIR="$HERE/inputs"
mkdir -p "$OUT_DIR" "$IN_DIR"

REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

CLIP_A="pocs/03-ltx-i2v/outputs/i2v.mp4"
if [[ ! -f "$CLIP_A" ]]; then
  echo "ERROR: $CLIP_A missing. Run POC 3 first."
  exit 1
fi

# Extract the last frame of clip A. ffmpeg's trick for "last frame":
# seek to near-end then grab the final frame.
LAST_FRAME="$IN_DIR/last_frame.png"
if [[ ! -f "$LAST_FRAME" ]]; then
  DUR=$(ffprobe -v error -show_entries format=duration -of csv="p=0" "$CLIP_A")
  # seek to (duration - 0.05s) and grab one frame
  SEEK=$(awk "BEGIN {print $DUR - 0.05}")
  ffmpeg -y -hide_banner -loglevel error \
    -ss "$SEEK" -i "$CLIP_A" -vframes 1 "$LAST_FRAME"
fi
cp "$LAST_FRAME" "$OUT_DIR/last_frame_a.png"

PROMPT="camera continues pulling back, revealing the shoreline and stormy sky, overcast light, 16mm grain, no figures"

/usr/bin/time -l -o "$OUT_DIR/time.txt" \
  uv run mlx_video.ltx_2.generate \
    --prompt "$PROMPT" \
    --seed 43 \
    --pipeline dev-two-stage \
    --model-repo prince-canuma/LTX-2.3-dev \
    --text-encoder-repo mlx-community/gemma-3-12b-it-bf16 \
    --width 512 --height 320 \
    --num-frames 73 --fps 24 \
    --image "$LAST_FRAME" \
    --image-strength 1.0 \
    --image-frame-idx 0 \
    --output-path "$OUT_DIR/clip_b.mp4" \
  2>&1 | tee "$OUT_DIR/stdout.log"

# Extract frame 0 of clip B for direct seam comparison
ffmpeg -y -hide_banner -loglevel error -i "$OUT_DIR/clip_b.mp4" -vframes 1 "$OUT_DIR/frame_0_b.png"

# Concat A + B for full-speed seam inspection
CONCAT_LIST="$OUT_DIR/concat.txt"
printf "file '%s'\nfile '%s'\n" \
  "$(cd "$(dirname "$CLIP_A")" && pwd)/$(basename "$CLIP_A")" \
  "$OUT_DIR/clip_b.mp4" > "$CONCAT_LIST"
ffmpeg -y -hide_banner -loglevel error \
  -f concat -safe 0 -i "$CONCAT_LIST" -c copy "$OUT_DIR/chained.mp4"

echo ""
echo "=== done ==="
ls -lh "$OUT_DIR"
echo ""
echo "Watch the seam: open $OUT_DIR/chained.mp4"
echo "Frame compare: open $OUT_DIR/last_frame_a.png $OUT_DIR/frame_0_b.png"
