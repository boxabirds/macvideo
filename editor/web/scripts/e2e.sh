#!/usr/bin/env bash
# Run Playwright from a known-clean local server state, then clean up again.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${WEB_DIR}/../.." && pwd)"

cleanup() {
  "${REPO_ROOT}/scripts/stop_editor.sh" 8000 5173
}

cleanup
trap cleanup EXIT

cd "${WEB_DIR}"
PLAYWRIGHT_BIN="${WEB_DIR}/node_modules/.bin/playwright"
if [[ ! -x "${PLAYWRIGHT_BIN}" ]]; then
  echo "[e2e] missing ${PLAYWRIGHT_BIN}; run bun install in ${WEB_DIR}" >&2
  exit 1
fi

echo "[e2e] suite=${EDITOR_E2E_SUITE:-fake-backed}; fake-backed Playwright uses isolated temp data"
"${PLAYWRIGHT_BIN}" test "$@"
