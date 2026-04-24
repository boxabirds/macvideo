#!/usr/bin/env bash
# Wait for all 3 songs' keyframes to exist, then serially render LTX + concat.
# Progress to stdout and progress.log.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROGRESS="$HERE/progress.log"

log() {
  echo "[$(date +'%H:%M:%S')] $*" | tee -a "$PROGRESS"
}

wait_for_keyframes() {
  local song=$1 count=$2
  local dir="$HERE/outputs/$song/keyframes"
  local last=0
  while :; do
    local have=$(ls "$dir"/*.png 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$have" -ge "$count" ]]; then
      log "  $song: all $have keyframes present"
      break
    fi
    if [[ "$have" != "$last" ]]; then
      log "  $song: keyframes $have / $count"
      last=$have
    fi
    sleep 30
  done
}

render_song() {
  local song=$1 filter=$2 expected=$3
  log ""
  log "### render $song ($filter, $expected shots)"
  wait_for_keyframes "$song" "$expected"
  log "  invoking render_clips + concat..."
  local audio="$HERE/../../music/${song}.wav"
  uv run python "$HERE/scripts/render_clips.py" \
    --song "$song" \
    --audio "$audio" \
    --shots "$HERE/outputs/$song/shots.json" \
    --run-dir "$HERE/outputs/$song" \
    --filter "$filter" 2>&1 | tee -a "$PROGRESS"
  if [[ -f "$HERE/outputs/$song/final.mp4" ]]; then
    log ">>> $song DONE: $HERE/outputs/$song/final.mp4"
  else
    log ">>> $song render completed without final.mp4 — check logs"
  fi
}

log "=== wait_and_render starting ==="

render_song my-little-blackbird "stained glass" 89
render_song chronophobia        "cyanotype"     67
render_song busy-invisible      "papercut"      84

log ""
log "=== all songs processed ==="
for song in my-little-blackbird chronophobia busy-invisible; do
  final="$HERE/outputs/$song/final.mp4"
  if [[ -f "$final" ]]; then
    sz=$(ls -lh "$final" | awk '{print $5}')
    log "  $song: $final ($sz)"
  else
    log "  $song: MISSING"
  fi
done
