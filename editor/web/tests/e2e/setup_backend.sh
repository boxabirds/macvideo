#!/usr/bin/env bash
# Start the FastAPI backend against a fresh temp dir pre-populated with the
# tiny-song fixture. Playwright's webServer invokes this script; lifespan will
# auto-import the fixture on startup.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
FIXTURES="${REPO_ROOT}/editor/server/tests/fixtures/tiny-song"

# Fresh temp dir per run so state doesn't leak between invocations.
E2E_ROOT="$(mktemp -d -t macvideo-e2e-XXXXXX)"
mkdir -p "${E2E_ROOT}/music" "${E2E_ROOT}/outputs"
cp "${FIXTURES}/music/"* "${E2E_ROOT}/music/"
cp -R "${FIXTURES}/outputs/tiny-song" "${E2E_ROOT}/outputs/"

export EDITOR_DB_PATH="${E2E_ROOT}/editor.db"
export EDITOR_MUSIC_DIR="${E2E_ROOT}/music"
export EDITOR_OUTPUTS_DIR="${E2E_ROOT}/outputs"

cd "${REPO_ROOT}"
exec uv run uvicorn editor.server.main:app --port 8000 --log-level warning
