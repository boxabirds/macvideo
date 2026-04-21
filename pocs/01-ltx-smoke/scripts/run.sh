#!/usr/bin/env bash
#
# POC 1 — LTX-2.3 smoke test on M5 Max.
# Run from repo root: bash pocs/01-ltx-smoke/scripts/run.sh
#
# First run downloads ~19 GB of weights to ~/.cache/huggingface/
# and may take 20–60 minutes. Subsequent runs just generate.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$HERE/outputs"
mkdir -p "$OUT_DIR"

REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

echo "=== mlx-video CLI help ==="
uv run mlx_video.ltx_2.generate --help | tee "$OUT_DIR/help.txt" | head -60
echo ""

echo "=== smoke generation (512x320, 72 frames @ 24fps, distilled) ==="
echo "First run will download ~19 GB. Be patient."
echo ""

/usr/bin/time -l -o "$OUT_DIR/time.txt" \
  uv run mlx_video.ltx_2.generate \
    --prompt "grey mist over peat bog, cold palette, overcast light, 16mm grain, no figures" \
    --pipeline distilled \
    --model-repo prince-canuma/LTX-2.3-distilled \
    --text-encoder-repo mlx-community/gemma-3-12b-it-bf16 \
    --width 512 --height 320 \
    --num-frames 72 --fps 24 \
    --output-path "$OUT_DIR/smoke.mp4" \
  2>&1 | tee "$OUT_DIR/stdout.log"

echo ""
echo "=== timing / memory ==="
cat "$OUT_DIR/time.txt"

echo ""
echo "=== output ==="
if [[ -f "$OUT_DIR/smoke.mp4" ]]; then
  ls -lh "$OUT_DIR/smoke.mp4"
  echo ""
  echo "Open with: open $OUT_DIR/smoke.mp4"
else
  echo "FAIL: smoke.mp4 not generated. Check $OUT_DIR/stdout.log"
  exit 1
fi
