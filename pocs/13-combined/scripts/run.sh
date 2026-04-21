#!/usr/bin/env bash
#
# POC 13 — LTX I2V for 3 keyframes + SINGLE continuous audio slice + concat.
# v2: uses gap-inclusive clip durations from lines.json so cuts land on lyric
# boundaries while audio plays continuously. Final video is re-encoded through
# libx264 + aac to avoid codec-mismatch stutters.

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
NEGATIVE="blurry, low quality, worst quality, distorted, deformed, watermark, text, subtitle, figures, crowd"
MOTION_PROMPT_BASE="gentle slow camera settle, the figure breathes and shifts slightly, ambient dust in the light, no abrupt motion"

NUM_LINES=$(uv run python -c "import json; print(len(json.load(open('$RUN_DIR/lines.json'))))")
echo "Lines: $NUM_LINES"

# Extract ONE continuous audio slice spanning all three lines.
AUDIO_START=$(uv run python -c "import json; print(json.load(open('$RUN_DIR/audio_span.json'))['start_t'])")
AUDIO_DUR=$(uv run python -c "import json; print(json.load(open('$RUN_DIR/audio_span.json'))['duration_s'])")
AUDIO_FULL="$RUN_DIR/audio_full.wav"
echo "Continuous audio: ${AUDIO_START}s for ${AUDIO_DUR}s"
ffmpeg -y -hide_banner -loglevel error \
  -ss "$AUDIO_START" -t "$AUDIO_DUR" -i "$TRACK" \
  -c:a pcm_s16le -ar 48000 "$AUDIO_FULL"

# Generate each LTX clip with gap-inclusive num_frames.
for IDX_1BASED in $(seq 1 "$NUM_LINES"); do
  IDX_PAD=$(printf "%02d" "$IDX_1BASED")
  KEYFRAME="$RUN_DIR/keyframe_${IDX_PAD}.png"
  CLIP="$RUN_DIR/clip_${IDX_PAD}.mp4"

  if [[ ! -f "$KEYFRAME" ]]; then
    echo "ERROR: $KEYFRAME missing." >&2
    exit 2
  fi

  NUM_FRAMES=$(uv run python -c "import json; d=json.load(open('$RUN_DIR/lines.json')); print(d[$IDX_1BASED-1]['num_frames'])")
  CLIP_DUR=$(uv run python -c "import json; d=json.load(open('$RUN_DIR/lines.json')); print(d[$IDX_1BASED-1]['actual_clip_duration_s'])")
  IMAGE_PROMPT=$(uv run python -c "import json; p=json.load(open('$RUN_DIR/prompts.json')); print(p['image_prompts_per_line'][$IDX_1BASED-1])")
  LTX_PROMPT="${MOTION_PROMPT_BASE}. ${IMAGE_PROMPT}"

  echo ""
  echo "=== Line $IDX_1BASED: LTX I2V (${NUM_FRAMES} frames, ${CLIP_DUR}s, gap-inclusive) ==="
  /usr/bin/time -l -o "$RUN_DIR/time-ltx-${IDX_PAD}.txt" \
    uv run mlx_video.ltx_2.generate \
      --prompt "$LTX_PROMPT" \
      --negative-prompt "$NEGATIVE" \
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

# Concat clips as a single re-encoded video stream (no audio).
# Re-encoding through libx264 normalises any codec drift between clips and
# avoids the stutter we saw with -c copy on mismatched streams.
CONCAT_LIST="$RUN_DIR/concat.txt"
: > "$CONCAT_LIST"
for IDX_1BASED in $(seq 1 "$NUM_LINES"); do
  IDX_PAD=$(printf "%02d" "$IDX_1BASED")
  echo "file '$RUN_DIR/clip_${IDX_PAD}.mp4'" >> "$CONCAT_LIST"
done

VIDEO_CONCAT="$RUN_DIR/video_concat.mp4"
ffmpeg -y -hide_banner -loglevel error \
  -f concat -safe 0 -i "$CONCAT_LIST" \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
  -an "$VIDEO_CONCAT"

# Mux concatenated video with ONE continuous audio slice.
ffmpeg -y -hide_banner -loglevel error \
  -i "$VIDEO_CONCAT" -i "$AUDIO_FULL" \
  -c:v copy -c:a aac -b:a 192k -shortest "$RUN_DIR/final.mp4"

# Persist LTX prompts + negative into prompts.json
uv run python - <<PY
import json
from pathlib import Path
run_dir = Path("$RUN_DIR")
prompts = json.loads((run_dir / "prompts.json").read_text())
prompts["ltx_motion_prompt_base"] = "$MOTION_PROMPT_BASE"
prompts["ltx_negative_prompt"] = "$NEGATIVE"
prompts["ltx_final_prompts_per_line"] = [
    f"$MOTION_PROMPT_BASE. " + p
    for p in prompts["image_prompts_per_line"]
]
prompts["audio_concat_strategy"] = "single continuous slice spanning line_1.start to line_N.end"
prompts["video_concat_strategy"] = "back-to-back clips with gap-inclusive durations; re-encoded libx264+aac"
(run_dir / "prompts.json").write_text(json.dumps(prompts, indent=2, default=str))
PY

echo ""
echo "=== done ==="
ls -lh "$RUN_DIR"
echo ""
echo "Watch: open $RUN_DIR/final.mp4"
