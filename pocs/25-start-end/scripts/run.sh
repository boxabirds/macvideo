#!/usr/bin/env bash
# POC 25 — first + last frame conditioning via PR #23.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

# Create timestamped run dir
TS="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="$HERE/outputs/$TS"
mkdir -p "$RUN_DIR"
ln -sfn "$TS" "$HERE/outputs/latest"
echo "Run dir: $RUN_DIR"

# Locate POC 13 keyframes
POC13="$(cd pocs/13-combined/outputs/latest && pwd -P)"
START="$POC13/keyframe_01.png"
END="$POC13/keyframe_03.png"
[[ -f "$START" ]] || { echo "ERROR: $START missing"; exit 1; }
[[ -f "$END" ]]   || { echo "ERROR: $END missing"; exit 1; }
cp "$START" "$RUN_DIR/start.png"
cp "$END"   "$RUN_DIR/end.png"
echo "Start: $START"
echo "End:   $END"

PROMPT="gentle slow camera settle, the narrator's world evolves subtly from the first moment to the last, charcoal textures, grainy paper, natural domestic light"
NEG="blurry, low quality, worst quality, distorted, watermark, subtitle"
COMMON=(
  --seed 42
  --pipeline dev-two-stage
  --model-repo prince-canuma/LTX-2.3-dev
  --text-encoder-repo mlx-community/gemma-3-12b-it-bf16
  --width 512 --height 320
  --num-frames 73 --fps 24
  --image-strength 1.0
  --image-frame-idx 0
  --negative-prompt "$NEG"
  --prompt "$PROMPT"
)

# 1. Control: only start
echo ""
echo "=== Control (start only) ==="
uv run mlx_video.ltx_2.generate \
  "${COMMON[@]}" \
  --image "$START" \
  --output-path "$RUN_DIR/control.mp4" \
  2>&1 | tee "$RUN_DIR/stdout-control.log"

# 2. End-conditioned: start + end
echo ""
echo "=== Both ends (start + end) ==="
uv run mlx_video.ltx_2.generate \
  "${COMMON[@]}" \
  --image "$START" \
  --end-image "$END" \
  --end-image-strength 1.0 \
  --output-path "$RUN_DIR/both_ends.mp4" \
  2>&1 | tee "$RUN_DIR/stdout-both.log"

# Extract comparison frames
for kind in control both; do
  src="$RUN_DIR/${kind/both/both_ends}.mp4"
  [[ -f "$src" ]] || continue
  ffmpeg -y -hide_banner -loglevel error -i "$src" -vframes 1 "$RUN_DIR/frame_00_${kind}.png"
  # Last frame: seek past the end
  DUR=$(ffprobe -v error -show_entries format=duration -of csv="p=0" "$src")
  SEEK=$(awk "BEGIN {print $DUR - 0.05}")
  ffmpeg -y -hide_banner -loglevel error -ss "$SEEK" -i "$src" -vframes 1 "$RUN_DIR/frame_last_${kind}.png"
done

# A/B HTML
cat > "$RUN_DIR/ab.html" <<HTML
<!doctype html><html><head><meta charset="utf-8"><title>POC 25 — start + end</title>
<style>
  :root{color-scheme:light dark}body{font-family:-apple-system,sans-serif;margin:1rem;max-width:1800px}
  .row{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:1rem}
  .cell{background:#0001;padding:8px;border-radius:6px}
  .cell h2,.cell h3{margin:0 0 6px}
  img,video{width:100%;display:block;background:#000}
  .pair{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  .sub{font-size:12px;color:#888}
</style></head><body>
<h1>POC 25 — first + last frame conditioning (PR #23)</h1>
<div class="row">
  <div class="cell"><h2>Start keyframe</h2><img src="start.png"><p class="sub">supplied as --image</p></div>
  <div class="cell"><h2>End keyframe</h2><img src="end.png"><p class="sub">supplied as --end-image in the right-hand column only</p></div>
</div>
<div class="row">
  <div class="cell">
    <h2>Control — start only</h2>
    <video src="control.mp4" controls preload="metadata" loop></video>
    <div class="pair">
      <div><h3>frame 0</h3><img src="frame_00_control.png"></div>
      <div><h3>last frame</h3><img src="frame_last_control.png"></div>
    </div>
  </div>
  <div class="cell">
    <h2>Start + end</h2>
    <video src="both_ends.mp4" controls preload="metadata" loop></video>
    <div class="pair">
      <div><h3>frame 0</h3><img src="frame_00_both.png"></div>
      <div><h3>last frame</h3><img src="frame_last_both.png"></div>
    </div>
  </div>
</div>
</body></html>
HTML

# Persist prompts
uv run python -c "
import json
json.dump({
  'start': '$START', 'end': '$END',
  'prompt': '$PROMPT', 'negative': '$NEG',
  'pipeline': 'dev-two-stage', 'seed': 42,
  'width': 512, 'height': 320, 'num_frames': 73, 'fps': 24,
  'image_strength': 1.0, 'end_image_strength': 1.0,
}, open('$RUN_DIR/prompts.json', 'w'), indent=2)
"

echo ""
echo "=== done ==="
echo "Watch A/B: open $RUN_DIR/ab.html"
