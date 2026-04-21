#!/usr/bin/env bash
#
# POC 12 step 2 — LTX I2V + audio slice + sync test.
# Requires prep_keyframe.py to have run first (produces line.json + keyframe.png).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$HERE/outputs"
mkdir -p "$OUT_DIR"

REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

LINE_JSON="$OUT_DIR/line.json"
KEYFRAME="$OUT_DIR/keyframe.png"

if [[ ! -f "$LINE_JSON" || ! -f "$KEYFRAME" ]]; then
  echo "ERROR: prep_keyframe.py hasn't run. Expected $LINE_JSON and $KEYFRAME."
  exit 1
fi

NUM_FRAMES=$(uv run python -c "import json; print(json.load(open('$LINE_JSON'))['num_frames'])")
START_T=$(uv run python -c "import json; print(json.load(open('$LINE_JSON'))['start_t'])")
END_T=$(uv run python -c "import json; print(json.load(open('$LINE_JSON'))['end_t'])")
CLIP_DUR=$(uv run python -c "import json; print(json.load(open('$LINE_JSON'))['actual_clip_duration_s'])")

PROMPT="slow gentle camera settle, the small black bird breathes and shifts on a dry-stone wall, northern English moorland dusk, 16mm grain, no figures, no text"

echo "=== LTX I2V (dev-two-stage, ${NUM_FRAMES} frames, I2V from keyframe) ==="
/usr/bin/time -l -o "$OUT_DIR/time-ltx.txt" \
  uv run mlx_video.ltx_2.generate \
    --prompt "$PROMPT" \
    --seed 42 \
    --pipeline dev-two-stage \
    --model-repo prince-canuma/LTX-2.3-dev \
    --text-encoder-repo mlx-community/gemma-3-12b-it-bf16 \
    --width 512 --height 320 \
    --num-frames "$NUM_FRAMES" --fps 24 \
    --image "$KEYFRAME" \
    --image-strength 1.0 \
    --image-frame-idx 0 \
    --output-path "$OUT_DIR/clip.mp4" \
  2>&1 | tee "$OUT_DIR/stdout-ltx.log"

echo ""
echo "=== Audio slice at [${START_T}, ${END_T}] ==="
ffmpeg -y -hide_banner -loglevel error \
  -ss "$START_T" -t "$CLIP_DUR" -i music/my-little-blackbird.wav \
  -c:a pcm_s16le -ar 48000 "$OUT_DIR/audio_slice.wav"

echo ""
echo "=== Combine video + audio slice -> sync_test.mp4 ==="
ffmpeg -y -hide_banner -loglevel error \
  -i "$OUT_DIR/clip.mp4" -i "$OUT_DIR/audio_slice.wav" \
  -c:v copy -c:a aac -shortest "$OUT_DIR/sync_test.mp4"

echo ""
echo "=== done ==="
ls -lh "$OUT_DIR"/*.mp4 "$OUT_DIR"/*.wav "$OUT_DIR"/*.png "$OUT_DIR"/*.json 2>/dev/null
echo ""
echo "Watch sync: open $OUT_DIR/sync_test.mp4"
