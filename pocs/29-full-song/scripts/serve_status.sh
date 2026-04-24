#!/usr/bin/env bash
# Run a status-regeneration loop + local HTTP server for the live status page.
# Kill with `kill <PID>` shown on startup.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUTS="$HERE/outputs"
PORT="${1:-8765}"

echo "Status page: http://localhost:${PORT}/status.html"
echo "Regenerating status.json every 30s..."
echo ""

# Background: status regen loop
(
  while true; do
    uv run python "$HERE/scripts/build_status.py" > /dev/null 2>&1 || true
    sleep 30
  done
) &
REGEN_PID=$!
echo "regen loop PID: $REGEN_PID"

# Foreground: http server in outputs/
cd "$OUTPUTS"
echo "Serving $OUTPUTS on :$PORT ..."
echo "Press Ctrl-C to stop."
# Trap to kill the regen loop on exit
trap "kill $REGEN_PID 2>/dev/null || true" EXIT INT TERM
SERVE_DIR="$OUTPUTS" python3 "$HERE/scripts/range_server.py" "$PORT"
