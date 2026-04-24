#!/usr/bin/env bash
#
# POC 23 render — re-run LTX using the snapped_shots.json from snap.py.
# Reuses POC 15's keyframes and audio handling; just swaps the shot plan.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

RUN_DIR="${1:-$HERE/outputs/latest}"
if [[ ! -d "$RUN_DIR" ]]; then
  echo "ERROR: $RUN_DIR missing. Run snap.py first or pass a run dir." >&2
  exit 1
fi
RUN_DIR="$(cd "$RUN_DIR" && pwd -P)"
echo "Using run dir: $RUN_DIR"

# We symlink POC 15's keyframes and the snapped shot plan into a run-compatible
# layout that POC 15's run.sh expects, then call that directly.
POC15_RUN="$(cd pocs/15-gap-interpolation/outputs/latest && pwd -P)"
if [[ ! -d "$POC15_RUN" ]]; then
  echo "ERROR: POC 15 output missing; snap.py needs a source plan there." >&2
  exit 1
fi

# Build a shadow directory whose structure matches POC 15 but with snapped shots
SHADOW="$RUN_DIR/shadow"
mkdir -p "$SHADOW"
cp "$POC15_RUN/character_brief.json" "$SHADOW/"
cp "$POC15_RUN/audio_span.json" "$SHADOW/"
cp "$POC15_RUN/prompts.json" "$SHADOW/"
cp "$RUN_DIR/snapped_shots.json" "$SHADOW/shots.json"
# Symlink keyframes
for kf in "$POC15_RUN"/keyframe_*.png; do
  ln -sf "$kf" "$SHADOW/$(basename "$kf")"
done

# Point POC 15 run.sh at the shadow by temporarily switching the `latest` symlink
# (safer: invoke a copy of POC 15's run.sh with an arg — but POC 15 reads from `latest`).
# We'll duplicate POC 15's logic inline here to avoid clobbering its run dir.

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
  KEYFRAME="$SHADOW/keyframe_${IDX_PAD}.png"
  CLIP="$SHADOW/clip_${IDX_PAD}.mp4"
  if [[ ! -f "$KEYFRAME" ]]; then
    echo "WARN: keyframe $IDX_PAD missing; skipping" >&2; continue
  fi

  NUM_FRAMES=$(uv run python -c "import json; s=json.load(open('$SHADOW/shots.json')); print(s[$IDX-1]['num_frames'])")
  IMAGE_PROMPT=$(uv run python -c "import json; s=json.load(open('$SHADOW/shots.json')); print(s[$IDX-1]['image_prompt'])")

  echo ""
  echo "=== Shot $IDX  frames=$NUM_FRAMES ==="
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

# Concat
CONCAT="$SHADOW/concat.txt"; : > "$CONCAT"
for IDX in $(seq 1 "$N_SHOTS"); do
  IDX_PAD=$(printf "%02d" "$IDX")
  [[ -f "$SHADOW/clip_${IDX_PAD}.mp4" ]] && echo "file '$SHADOW/clip_${IDX_PAD}.mp4'" >> "$CONCAT"
done
ffmpeg -y -hide_banner -loglevel error -f concat -safe 0 -i "$CONCAT" \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -an "$SHADOW/video_concat.mp4"
ffmpeg -y -hide_banner -loglevel error -i "$SHADOW/video_concat.mp4" -i "$AUDIO_FULL" \
  -c:v copy -c:a aac -b:a 192k -shortest "$RUN_DIR/final.mp4"

# A/B HTML
cat > "$RUN_DIR/snap_vs_original.html" <<HTML
<!doctype html><html><head><meta charset="utf-8"><title>Snap vs original</title>
<style>body{font-family:-apple-system,sans-serif;margin:1rem}
.ab{display:grid;grid-template-columns:1fr 1fr;gap:12px}
video{width:100%;background:#000}
h2{margin:0}
</style></head><body>
<h1>POC 23 — Snap to event A/B</h1>
<div class="ab">
  <div><h2>Original (POC 15)</h2>
    <video src="../../../15-gap-interpolation/outputs/latest/final.mp4" controls preload="metadata"></video>
    <p><a href="../../../15-gap-interpolation/outputs/latest/shots.json">shots.json</a></p>
  </div>
  <div><h2>Snapped (±100 ms to musical events)</h2>
    <video src="final.mp4" controls preload="metadata"></video>
    <p><a href="snapped_shots.json">snapped_shots.json</a> · <a href="snap_report.md">snap_report.md</a></p>
  </div>
</div>
</body></html>
HTML

echo ""
echo "=== done ==="
echo "Watch A/B: open $RUN_DIR/snap_vs_original.html"
