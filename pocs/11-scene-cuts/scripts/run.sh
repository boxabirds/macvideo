#!/usr/bin/env bash
#
# POC 11 — 4 independent shots, same style base, hard-cut concat.
# Tests cohesion across cuts, which is what real music-video assembly needs.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$HERE/outputs"
mkdir -p "$OUT_DIR"

REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

STYLE="overcast northern English light, 16mm film grain, cold palette, muted slate and ochre, cinematic wide shot"

SCENES=(
  "eroded gritstone edge at dusk, slow drift, low mist rolling between hills, no figures"
  "disused slate quarry, wet black rock faces, standing water at the base, slow push in, no figures"
  "close macro of rain hitting dark stone, shallow focus, slow rivulets tracing lichen, no figures"
  "aerial drift over peat moorland, cotton grass patches, heavy cloud, no figures"
)
NAMES=(edge quarry stone moor)

gen() {
  local idx="$1"
  local name="${NAMES[$idx]}"
  local subject="${SCENES[$idx]}"
  local out="$OUT_DIR/${idx}_${name}.mp4"
  echo ""
  echo "=== ${idx}_${name} ==="
  /usr/bin/time -l -o "$OUT_DIR/time-${idx}.txt" \
    uv run mlx_video.ltx_2.generate \
      --prompt "${subject}. ${STYLE}" \
      --seed 42 \
      --pipeline dev-two-stage \
      --model-repo prince-canuma/LTX-2.3-dev \
      --text-encoder-repo mlx-community/gemma-3-12b-it-bf16 \
      --width 512 --height 320 \
      --num-frames 73 --fps 24 \
      --output-path "$out" \
    2>&1 | tee "$OUT_DIR/stdout-${idx}.log"
}

for i in 0 1 2 3; do
  gen "$i"
done

# Concat with hard cuts
CONCAT_LIST="$OUT_DIR/concat.txt"
: > "$CONCAT_LIST"
for i in 0 1 2 3; do
  echo "file '${OUT_DIR}/${i}_${NAMES[$i]}.mp4'" >> "$CONCAT_LIST"
done
ffmpeg -y -hide_banner -loglevel error -f concat -safe 0 \
  -i "$CONCAT_LIST" -c copy "$OUT_DIR/cuts.mp4"

echo ""
echo "=== done ==="
ls -lh "$OUT_DIR"/*.mp4
echo ""
echo "Watch: open $OUT_DIR/cuts.mp4"
