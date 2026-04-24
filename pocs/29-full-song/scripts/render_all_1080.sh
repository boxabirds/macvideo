#!/usr/bin/env bash
# Render all 3 songs sequentially at 1920x1088 / 30fps.
# Resumable — render_clips.py skips existing clips.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROGRESS="$HERE/progress.log"

log() { echo "[$(date +'%m-%d %H:%M:%S')] $*" | tee -a "$PROGRESS"; }

log ""
log "=== render_all_1080 starting ==="

render_song() {
  local song=$1 filter=$2
  log ""
  log "### render $song ($filter) @ 1920x1088 / 30fps"
  local audio="$HERE/../../music/${song}.wav"
  uv run python "$HERE/scripts/render_clips.py" \
    --song "$song" \
    --audio "$audio" \
    --shots "$HERE/outputs/$song/shots.json" \
    --run-dir "$HERE/outputs/$song" \
    --filter "$filter" 2>&1 | tee -a "$PROGRESS"
  local final="$HERE/outputs/$song/final.mp4"
  if [[ -f "$final" ]]; then
    log ">>> $song: $(ls -lh $final | awk '{print $5}')"
  else
    log ">>> $song: final.mp4 MISSING"
  fi
}

render_song my-little-blackbird "stained glass"
render_song chronophobia        "cyanotype"
render_song busy-invisible      "papercut"

log ""
log "=== render_all_1080 done ==="
