#!/usr/bin/env bash
#
# POC 2 — LTX-2.3 audio-conditioning A/B/C test.
# Three generations, same prompt + seed, varying the audio input.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$HERE/outputs"
IN_DIR="$HERE/inputs"
mkdir -p "$OUT_DIR" "$IN_DIR"

REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

# Slice audio inputs from user's music/ if not already present
if [[ ! -f "$IN_DIR/ambient.wav" ]]; then
  echo "Slicing ambient.wav from chronophobia..."
  ffmpeg -y -hide_banner -loglevel error \
    -ss 100 -i music/chronophobia.wav -t 5 \
    -c:a pcm_s16le -ar 48000 "$IN_DIR/ambient.wav"
fi
if [[ ! -f "$IN_DIR/beat.wav" ]]; then
  echo "Slicing beat.wav from busy-invisible..."
  ffmpeg -y -hide_banner -loglevel error \
    -ss 100 -i music/busy-invisible.wav -t 5 \
    -c:a pcm_s16le -ar 48000 "$IN_DIR/beat.wav"
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
    --pipeline distilled \
    --model-repo prince-canuma/LTX-2.3-distilled \
    --text-encoder-repo mlx-community/gemma-3-12b-it-bf16 \
    --width "$WIDTH" --height "$HEIGHT" \
    --num-frames "$NUM_FRAMES" --fps "$FPS" \
    "$@" \
    --output-path "$OUT_DIR/${label}.mp4" \
    2>&1 | tee "$OUT_DIR/stdout-${label}.log"
}

gen "a_no_audio"
gen "b_ambient" --audio-file "$IN_DIR/ambient.wav"
gen "c_beat"    --audio-file "$IN_DIR/beat.wav"

echo ""
echo "=== done ==="
ls -lh "$OUT_DIR"/*.mp4
echo ""
echo "Compare: open $OUT_DIR/a_no_audio.mp4 $OUT_DIR/b_ambient.mp4 $OUT_DIR/c_beat.mp4"
