#!/usr/bin/env bash
#
# POC 24 render — re-run LTX using the densified_shots.json from densify.py.
# Uses POC 15's keyframes by parent_shot_index lookup.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

RUN_DIR="${1:-$HERE/outputs/latest}"
[[ -d "$RUN_DIR" ]] || { echo "ERROR: $RUN_DIR missing"; exit 1; }
RUN_DIR="$(cd "$RUN_DIR" && pwd -P)"
echo "Using run dir: $RUN_DIR"

POC15_RUN="$(cd pocs/15-gap-interpolation/outputs/latest && pwd -P)"
[[ -d "$POC15_RUN" ]] || { echo "ERROR: POC 15 output missing"; exit 1; }

SHADOW="$RUN_DIR/shadow"
mkdir -p "$SHADOW"
cp "$POC15_RUN/character_brief.json" "$SHADOW/"
cp "$POC15_RUN/audio_span.json"      "$SHADOW/"
cp "$POC15_RUN/prompts.json"         "$SHADOW/"
cp "$RUN_DIR/densified_shots.json"   "$SHADOW/shots.json"

TRACK="music/my-little-blackbird.wav"
MOTION_PROMPT_BASE="gentle slow camera settle, the figure breathes and shifts slightly, ambient dust in the light, no abrupt motion"
TECH_NEGATIVE="blurry, low quality, worst quality, distorted, watermark, subtitle"

N_SHOTS=$(uv run python -c "import json; print(len(json.load(open('$SHADOW/shots.json'))))")
AUDIO_START=$(uv run python -c "import json; print(json.load(open('$SHADOW/audio_span.json'))['start_t'])")
AUDIO_DUR=$(uv run python -c "import json; print(json.load(open('$SHADOW/audio_span.json'))['duration_s'])")
AUDIO_FULL="$SHADOW/audio_full.wav"
ffmpeg -y -hide_banner -loglevel error -ss "$AUDIO_START" -t "$AUDIO_DUR" -i "$TRACK" \
  -c:a pcm_s16le -ar 48000 "$AUDIO_FULL"

for IDX in $(seq 1 "$N_SHOTS"); do
  IDX_PAD=$(printf "%02d" "$IDX")
  CLIP="$SHADOW/clip_${IDX_PAD}.mp4"

  # Find parent shot index (1-based) for this shot; fall back to self index
  PARENT=$(uv run python -c "
import json
s = json.load(open('$SHADOW/shots.json'))
shot = s[$IDX-1]
print(shot.get('parent_shot_index', $IDX-1) + 1)
")
  PARENT_PAD=$(printf "%02d" "$PARENT")
  KEYFRAME="$POC15_RUN/keyframe_${PARENT_PAD}.png"
  if [[ ! -f "$KEYFRAME" ]]; then
    echo "WARN: parent keyframe $PARENT_PAD missing for shot $IDX_PAD; skipping"
    continue
  fi

  NUM_FRAMES=$(uv run python -c "import json; s=json.load(open('$SHADOW/shots.json')); print(s[$IDX-1]['num_frames'])")
  IMAGE_PROMPT=$(uv run python -c "import json; s=json.load(open('$SHADOW/shots.json')); print(s[$IDX-1]['image_prompt'])")

  echo ""
  echo "=== Shot $IDX  (parent $PARENT, frames=$NUM_FRAMES) ==="
  uv run mlx_video.ltx_2.generate \
    --prompt "${MOTION_PROMPT_BASE}. ${IMAGE_PROMPT}" \
    --negative-prompt "$TECH_NEGATIVE" \
    --seed 42 \
    --pipeline dev-two-stage \
    --model-repo prince-canuma/LTX-2.3-dev \
    --text-encoder-repo mlx-community/gemma-3-12b-it-bf16 \
    --width 512 --height 320 \
    --num-frames "$NUM_FRAMES" --fps 24 \
    --image "$KEYFRAME" \
    --image-strength 1.0 \
    --image-frame-idx 0 \
    --output-path "$CLIP" \
    2>&1 | tee "$SHADOW/stdout-ltx-${IDX_PAD}.log"
done

CONCAT="$SHADOW/concat.txt"; : > "$CONCAT"
for IDX in $(seq 1 "$N_SHOTS"); do
  IDX_PAD=$(printf "%02d" "$IDX")
  [[ -f "$SHADOW/clip_${IDX_PAD}.mp4" ]] && echo "file '$SHADOW/clip_${IDX_PAD}.mp4'" >> "$CONCAT"
done
ffmpeg -y -hide_banner -loglevel error -f concat -safe 0 -i "$CONCAT" \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -an "$SHADOW/video_concat.mp4"
ffmpeg -y -hide_banner -loglevel error -i "$SHADOW/video_concat.mp4" -i "$AUDIO_FULL" \
  -c:v copy -c:a aac -b:a 192k -shortest "$RUN_DIR/final.mp4"

cat > "$RUN_DIR/densify_vs_original.html" <<HTML
<!doctype html><html><head><meta charset="utf-8"><title>Densify vs original</title>
<style>body{font-family:-apple-system,sans-serif;margin:1rem}
.ab{display:grid;grid-template-columns:1fr 1fr;gap:12px}
video{width:100%;background:#000}
h2{margin:0}
</style></head><body>
<h1>POC 24 — Event-densified cuts A/B</h1>
<div class="ab">
  <div><h2>Original (POC 15)</h2>
    <video src="../../../15-gap-interpolation/outputs/latest/final.mp4" controls preload="metadata"></video>
  </div>
  <div><h2>Densified (split long shots at strong drum onsets)</h2>
    <video src="final.mp4" controls preload="metadata"></video>
    <p><a href="densified_shots.json">densified_shots.json</a> · <a href="densify_report.md">densify_report.md</a></p>
  </div>
</div>
</body></html>
HTML

echo ""
echo "=== done ==="
echo "Watch A/B: open $RUN_DIR/densify_vs_original.html"
