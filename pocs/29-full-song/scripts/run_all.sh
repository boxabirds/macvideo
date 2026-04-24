#!/usr/bin/env bash
# Autonomous driver: run all 3 songs end-to-end.
# Resumable — each step checks for prior outputs before re-running.
#
# Writes progress to progress.log so user can inspect on return.
set -uo pipefail  # not -e; we want to keep going on per-song failures

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROGRESS_LOG="$HERE/progress.log"

log() {
  echo "[$(date +'%H:%M:%S')] $*" | tee -a "$PROGRESS_LOG"
}

log "=== run_all starting ==="

for entry in \
  "my-little-blackbird|stained glass" \
  "chronophobia|cyanotype" \
  "busy-invisible|papercut" \
; do
  song="${entry%%|*}"
  filter="${entry#*|}"

  log ""
  log "### $song / filter=$filter"
  if bash "$HERE/scripts/pipeline.sh" "$song" "$filter" 2>&1 | tee -a "$PROGRESS_LOG"; then
    log ">>> $song completed"
  else
    log ">>> $song FAILED (exit $?)"
  fi
done

log ""
log "=== run_all done ==="
log "outputs:"
for song in my-little-blackbird chronophobia busy-invisible; do
  final="$HERE/outputs/$song/final.mp4"
  if [[ -f "$final" ]]; then
    sz=$(ls -lh "$final" | awk '{print $5}')
    log "  $song: $final ($sz)"
  else
    log "  $song: MISSING"
  fi
done
