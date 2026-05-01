#!/usr/bin/env bash
# Run Playwright on an isolated test stack, separate from local dev servers.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${WEB_DIR}/../.." && pwd)"

export EDITOR_E2E_API_PORT="${EDITOR_E2E_API_PORT:-18000}"
export EDITOR_E2E_WEB_PORT="${EDITOR_E2E_WEB_PORT:-15173}"
export EDITOR_API_PORT="${EDITOR_E2E_API_PORT}"
export EDITOR_WEB_PORT="${EDITOR_E2E_WEB_PORT}"

cleanup() {
  "${REPO_ROOT}/scripts/stop_editor.sh" "${EDITOR_E2E_API_PORT}" "${EDITOR_E2E_WEB_PORT}"
}

cleanup
trap cleanup EXIT

cd "${WEB_DIR}"
PLAYWRIGHT_BIN="${WEB_DIR}/node_modules/.bin/playwright"
if [[ ! -x "${PLAYWRIGHT_BIN}" ]]; then
  echo "[e2e] missing ${PLAYWRIGHT_BIN}; run bun install in ${WEB_DIR}" >&2
  exit 1
fi

echo "[e2e] suite=${EDITOR_E2E_SUITE:-fake-backed}; api=:${EDITOR_E2E_API_PORT}; web=:${EDITOR_E2E_WEB_PORT}; fake-backed Playwright uses isolated temp data"
"${PLAYWRIGHT_BIN}" test "$@"
