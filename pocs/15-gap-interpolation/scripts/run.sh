#!/usr/bin/env bash
#
# POC 15 — LTX I2V for N lyric + K gap shots, then single-audio concat.
# Forks POC 13 v2's run.sh; drives shot sequence from shots.json instead of
# lines.json because interpolated gap shots are first-class here.

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

TRACK="music/my-little-blackbird.wav"
MOTION_PROMPT_BASE="gentle slow camera settle, the figure breathes and shifts slightly, ambient dust in the light, no abrupt motion"
# Technical-only negative; no content negatives (affirmative prompts do that work)
TECH_NEGATIVE="blurry, low quality, worst quality, distorted, watermark, subtitle"

N_SHOTS=$(uv run python -c "import json; print(len(json.load(open('$RUN_DIR/shots.json'))))")
echo "Shots: $N_SHOTS"

# Single continuous audio slice for the whole sequence
AUDIO_START=$(uv run python -c "import json; print(json.load(open('$RUN_DIR/audio_span.json'))['start_t'])")
AUDIO_DUR=$(uv run python -c "import json; print(json.load(open('$RUN_DIR/audio_span.json'))['duration_s'])")
AUDIO_FULL="$RUN_DIR/audio_full.wav"
echo "Continuous audio: ${AUDIO_START}s for ${AUDIO_DUR}s"
ffmpeg -y -hide_banner -loglevel error \
  -ss "$AUDIO_START" -t "$AUDIO_DUR" -i "$TRACK" \
  -c:a pcm_s16le -ar 48000 "$AUDIO_FULL"

for IDX in $(seq 1 "$N_SHOTS"); do
  IDX_PAD=$(printf "%02d" "$IDX")
  KEYFRAME="$RUN_DIR/keyframe_${IDX_PAD}.png"
  CLIP="$RUN_DIR/clip_${IDX_PAD}.mp4"

  if [[ ! -f "$KEYFRAME" ]]; then
    echo "ERROR: $KEYFRAME missing." >&2
    exit 2
  fi

  NUM_FRAMES=$(uv run python -c "import json; s=json.load(open('$RUN_DIR/shots.json')); print(s[$IDX-1]['num_frames'])")
  SHOT_TYPE=$(uv run python -c "import json; s=json.load(open('$RUN_DIR/shots.json')); print(s[$IDX-1]['type'])")
  IMAGE_PROMPT=$(uv run python -c "import json; s=json.load(open('$RUN_DIR/shots.json')); print(s[$IDX-1]['image_prompt'])")
  LTX_PROMPT="${MOTION_PROMPT_BASE}. ${IMAGE_PROMPT}"

  echo ""
  echo "=== Shot $IDX ($SHOT_TYPE, $NUM_FRAMES frames) ==="
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

# Concat video (re-encode for codec sanity) then mux with audio
CONCAT_LIST="$RUN_DIR/concat.txt"
: > "$CONCAT_LIST"
for IDX in $(seq 1 "$N_SHOTS"); do
  IDX_PAD=$(printf "%02d" "$IDX")
  echo "file '$RUN_DIR/clip_${IDX_PAD}.mp4'" >> "$CONCAT_LIST"
done

VIDEO_CONCAT="$RUN_DIR/video_concat.mp4"
ffmpeg -y -hide_banner -loglevel error \
  -f concat -safe 0 -i "$CONCAT_LIST" \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
  -an "$VIDEO_CONCAT"

ffmpeg -y -hide_banner -loglevel error \
  -i "$VIDEO_CONCAT" -i "$AUDIO_FULL" \
  -c:v copy -c:a aac -b:a 192k -shortest "$RUN_DIR/final.mp4"

# Append LTX-side prompts to prompts.json
uv run python - <<PY
import json
from pathlib import Path
run_dir = Path("$RUN_DIR")
prompts = json.loads((run_dir / "prompts.json").read_text())
prompts["ltx_motion_prompt_base"] = "$MOTION_PROMPT_BASE"
prompts["ltx_technical_negative"] = "$TECH_NEGATIVE"
prompts["ltx_content_negative"] = "none — affirmative prompts only"
prompts["ltx_final_prompts_per_shot"] = {
    f"shot_{i+1:02d}": f"$MOTION_PROMPT_BASE. " + s["image_prompt"]
    for i, s in enumerate(json.loads((run_dir / "shots.json").read_text()))
}
(run_dir / "prompts.json").write_text(json.dumps(prompts, indent=2, default=str))
PY

echo ""
echo "=== done ==="
ls -lh "$RUN_DIR"
echo ""
echo "Watch: open $RUN_DIR/final.mp4"
