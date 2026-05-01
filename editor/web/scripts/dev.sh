#!/usr/bin/env bash
# Dev launcher: frees ports 8000 (backend) and 5173 (vite), starts both.
# Ctrl-C stops both.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${WEB_DIR}/../.." && pwd)"

"${SCRIPT_DIR}/teardown_servers.sh" 8000 5173

# Unit tests may set fake subprocess overrides. Local dev must exercise the
# product pipeline, so fake overrides are removed only for the backend command.
BACKEND_ENV=(
  env
  -u EDITOR_FAKE_GEN_KEYFRAMES
  -u EDITOR_FAKE_RENDER_CLIPS
  -u EDITOR_FAKE_WHISPERX_ALIGN
  -u EDITOR_FAKE_DEMUCS
  -u EDITOR_FAKE_WHISPERX_TRANSCRIBE
)

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    echo "[dev] stopping backend (pid ${BACKEND_PID})"
    kill "${BACKEND_PID}" 2>/dev/null || true
    wait "${BACKEND_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "[dev] starting backend on :8000"
( cd "${REPO_ROOT}" && "${BACKEND_ENV[@]}" uv run uvicorn editor.server.main:app --port 8000 --log-level info ) &
BACKEND_PID=$!

echo "[dev] starting vite on :5173"
cd "${WEB_DIR}"
vite
