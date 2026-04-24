#!/usr/bin/env bash
# Orchestrator: for a given song, build shot list, run keyframe gen, render
# clips, concat + mux. Resumable — re-running picks up where it left off.
set -euo pipefail

SONG="$1"
FILTER="$2"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"

AUDIO="$REPO_ROOT/music/${SONG}.wav"
LYRICS="$REPO_ROOT/music/${SONG}.txt"
WX="$HERE/whisperx_cache/${SONG}.aligned.json"

for p in "$AUDIO" "$LYRICS" "$WX"; do
  [[ -f "$p" ]] || { echo "ERROR: missing $p"; exit 1; }
done

# Use a stable per-song dir so retries accumulate
RUN_DIR="$HERE/outputs/$SONG"
mkdir -p "$RUN_DIR"

# Also maintain a latest symlink for cross-song reference
ln -sfn "$SONG" "$HERE/outputs/latest-$SONG" 2>/dev/null || true

SHOTS_JSON="$RUN_DIR/shots.json"
if [[ ! -f "$SHOTS_JSON" ]]; then
  echo "[1/3] build shot list"
  uv run python "$HERE/scripts/make_shots.py" \
    --song "$SONG" --whisperx "$WX" --lyrics "$LYRICS" --out "$SHOTS_JSON"
else
  echo "[1/3] shots.json cached"
fi

echo ""
echo "[2/3] keyframes (Pass A/C/B + Gemini image)"
uv run python "$HERE/scripts/gen_keyframes.py" \
  --song "$SONG" --lyrics "$LYRICS" --shots "$SHOTS_JSON" \
  --run-dir "$RUN_DIR" --filter "$FILTER" --abstraction 25

echo ""
echo "[3/3] render clips + concat + mux"
uv run python "$HERE/scripts/render_clips.py" \
  --song "$SONG" --audio "$AUDIO" --shots "$SHOTS_JSON" \
  --run-dir "$RUN_DIR" --filter "$FILTER"

echo ""
echo "=== $SONG done ==="
echo "final: $RUN_DIR/final.mp4"
