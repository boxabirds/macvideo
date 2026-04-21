#!/usr/bin/env bash
#
# POC 16 — LTX I2V per shot, motion prompt derived from camera_intent.
# Concat clips into silent final.mp4 (pathological test: no meaningful audio).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

RUN_DIR="$HERE/outputs/latest"
if [[ ! -d "$RUN_DIR" ]]; then
  echo "ERROR: $RUN_DIR missing. Run prep.py first." >&2
  exit 1
fi
RUN_DIR="$(cd "$RUN_DIR" && pwd -P)"
echo "Using run dir: $RUN_DIR"

TECH_NEGATIVE="blurry, low quality, worst quality, distorted, watermark, subtitle"

N_SHOTS=$(uv run python -c "import json; print(len(json.load(open('$RUN_DIR/shots.json'))))")
echo "Shots: $N_SHOTS"

# Camera-intent vocabulary → LTX motion phrase
camera_motion() {
  case "$1" in
    "static hold")     echo "static frame, no camera movement, composition held completely still, subjects barely move" ;;
    "slow push in")    echo "camera slowly pushes forward toward the subject, continuous gentle movement in, subject grows larger in frame" ;;
    "slow pull back")  echo "camera slowly pulls back from the subject, revealing more of the surrounding space as it retreats" ;;
    "pan left")        echo "camera slowly pans left, revealing new space on the left side of the frame" ;;
    "pan right")       echo "camera slowly pans right, revealing new space on the right side of the frame" ;;
    "tilt up")         echo "camera slowly tilts upward, revealing what rises above the frame" ;;
    "tilt down")       echo "camera slowly tilts downward, revealing what sits below the frame" ;;
    "orbit left")      echo "camera orbits gently to the left around the subject, subject remaining centred" ;;
    "orbit right")     echo "camera orbits gently to the right around the subject, subject remaining centred" ;;
    "handheld drift")  echo "subtle handheld camera drift, small organic movements, no clear direction" ;;
    "held on detail")  echo "camera held completely still on a specific detail, movement only within the frame, no camera motion" ;;
    *)                 echo "gentle slow camera settle, ambient motion within the frame" ;;
  esac
}

for IDX in $(seq 1 "$N_SHOTS"); do
  IDX_PAD=$(printf "%02d" "$IDX")
  KEYFRAME="$RUN_DIR/keyframe_${IDX_PAD}.png"
  CLIP="$RUN_DIR/clip_${IDX_PAD}.mp4"

  if [[ ! -f "$KEYFRAME" ]]; then
    echo "ERROR: $KEYFRAME missing." >&2
    exit 2
  fi

  NUM_FRAMES=$(uv run python -c "import json; s=json.load(open('$RUN_DIR/shots.json')); print(s[$IDX-1]['num_frames'])")
  CAMERA_INTENT=$(uv run python -c "import json; s=json.load(open('$RUN_DIR/shots.json')); print(s[$IDX-1]['camera_intent'])")
  IMAGE_PROMPT=$(uv run python -c "import json; s=json.load(open('$RUN_DIR/shots.json')); print(s[$IDX-1]['image_prompt'])")
  BEAT=$(uv run python -c "import json; s=json.load(open('$RUN_DIR/shots.json')); print(s[$IDX-1]['beat'])")

  MOTION=$(camera_motion "$CAMERA_INTENT")
  LTX_PROMPT="${MOTION}. ${IMAGE_PROMPT}"

  echo ""
  echo "=== Shot $IDX  camera='${CAMERA_INTENT}'  frames=${NUM_FRAMES} ==="
  echo "  beat: $BEAT"
  /usr/bin/time -l -o "$RUN_DIR/time-ltx-${IDX_PAD}.txt" \
    uv run mlx_video.ltx_2.generate \
      --prompt "$LTX_PROMPT" \
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
    2>&1 | tee "$RUN_DIR/stdout-ltx-${IDX_PAD}.log"
done

# Concat video — no audio (pathological test uses cloned lines, no meaningful song timing)
CONCAT_LIST="$RUN_DIR/concat.txt"
: > "$CONCAT_LIST"
for IDX in $(seq 1 "$N_SHOTS"); do
  IDX_PAD=$(printf "%02d" "$IDX")
  echo "file '$RUN_DIR/clip_${IDX_PAD}.mp4'" >> "$CONCAT_LIST"
done

ffmpeg -y -hide_banner -loglevel error \
  -f concat -safe 0 -i "$CONCAT_LIST" \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
  -an "$RUN_DIR/final.mp4"

# Append LTX-side prompts to prompts.json
uv run python - <<PY
import json
from pathlib import Path
run_dir = Path("$RUN_DIR")
prompts = json.loads((run_dir / "prompts.json").read_text())
shots = json.loads((run_dir / "shots.json").read_text())

prompts["ltx_technical_negative"] = "$TECH_NEGATIVE"
prompts["ltx_motion_mapping"] = {
    "source": "camera_intent from storyboard",
    "note": "hardcoded shell-side map in run.sh; each camera_intent resolves to one LTX motion phrase"
}
prompts["ltx_final_prompts_per_shot"] = {
    f"shot_{s['index']:02d}": {
        "camera_intent": s["camera_intent"],
        "image_prompt": s["image_prompt"],
    } for s in shots
}
(run_dir / "prompts.json").write_text(json.dumps(prompts, indent=2, default=str))
PY

echo ""
echo "=== done ==="
ls -lh "$RUN_DIR"
echo ""
echo "Watch: open $RUN_DIR/final.mp4"
