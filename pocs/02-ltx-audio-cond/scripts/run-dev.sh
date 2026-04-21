#!/usr/bin/env bash
#
# POC 2 follow-up — same A/B test, on the dev pipeline.
# Verifies that audio conditioning actually differentiates motion when CFG is applied.
# Distilled proved inert because it has no audio_cfg_scale path. Dev does.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$HERE/outputs"
IN_DIR="$HERE/inputs"
mkdir -p "$OUT_DIR"

REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

# Reuse slices from distilled run
if [[ ! -f "$IN_DIR/ambient.wav" || ! -f "$IN_DIR/beat.wav" ]]; then
  echo "ERROR: input slices missing. Run scripts/run.sh first to create them."
  exit 1
fi

PROMPT="slow drift across a dark ocean surface, moonlight, 16mm grain, no figures"
SEED=42
WIDTH=512
HEIGHT=320
NUM_FRAMES=121   # 1 + 8*15; ~5s at 24fps
FPS=24

gen() {
  local label="$1"; shift
  echo ""
  echo "=== $label ==="
  uv run mlx_video.ltx_2.generate \
    --prompt "$PROMPT" \
    --seed "$SEED" \
    --pipeline dev \
    --model-repo prince-canuma/LTX-2.3-dev \
    --text-encoder-repo mlx-community/gemma-3-12b-it-bf16 \
    --width "$WIDTH" --height "$HEIGHT" \
    --num-frames "$NUM_FRAMES" --fps "$FPS" \
    "$@" \
    --output-path "$OUT_DIR/${label}.mp4" \
    2>&1 | tee "$OUT_DIR/stdout-${label}.log"
}

gen "b_ambient_dev" --audio-file "$IN_DIR/ambient.wav"
gen "c_beat_dev"    --audio-file "$IN_DIR/beat.wav"

echo ""
echo "=== done ==="
ls -lh "$OUT_DIR"/*_dev.mp4
echo ""
echo "Compare: open $OUT_DIR/b_ambient_dev.mp4 $OUT_DIR/c_beat_dev.mp4"
