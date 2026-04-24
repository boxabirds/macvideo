#!/usr/bin/env bash
# Dev launcher: frees ports 8000 (backend) and 5173 (vite), starts both.
# Ctrl-C stops both.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${WEB_DIR}/../.." && pwd)"

kill_port() {
  local port=$1
  local pids
  pids=$(lsof -ti ":${port}" 2>/dev/null || true)
  if [[ -n "${pids}" ]]; then
    echo "[dev] freeing port ${port} (killing ${pids})"
    # shellcheck disable=SC2086
    kill -9 ${pids} 2>/dev/null || true
    sleep 0.2
  fi
}

kill_port 8000
kill_port 5173

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
    echo "[dev] stopping backend (pid ${BACKEND_PID})"
    kill "${BACKEND_PID}" 2>/dev/null || true
    wait "${BACKEND_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "[dev] starting backend on :8000"
( cd "${REPO_ROOT}" && uv run uvicorn editor.server.main:app --port 8000 --log-level info ) &
BACKEND_PID=$!

echo "[dev] starting vite on :5173"
cd "${WEB_DIR}"
vite
