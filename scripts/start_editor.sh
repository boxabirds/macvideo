#!/usr/bin/env bash
# Start backend and frontend from a known-good local process state.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WEB_DIR="${REPO_ROOT}/editor/web"

"${REPO_ROOT}/scripts/stop_editor.sh" 8000 5173

if [[ "${SKIP_DIAGNOSTICS:-0}" != "1" ]]; then
  uv run python "${REPO_ROOT}/scripts/check_dev_environment.py" --mode dev
fi

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
bun run dev:vite-only
