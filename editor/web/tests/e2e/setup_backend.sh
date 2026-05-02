#!/usr/bin/env bash
# Start the FastAPI backend against a fresh temp dir pre-populated with the
# tiny-song fixture. Playwright's webServer invokes this script; lifespan will
# auto-import the fixture on startup.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
FIXTURES_ROOT="${REPO_ROOT}/editor/server/tests/fixtures"
FIXTURES="${FIXTURES_ROOT}/tiny-song"
API_PORT="${EDITOR_E2E_API_PORT:-${EDITOR_API_PORT:-18000}}"

# Build any fixtures that are not committed (idempotent).
uv run python "${FIXTURES_ROOT}/_build_tiny_song.py" >/dev/null
uv run python "${FIXTURES_ROOT}/_build_fresh_songs.py" >/dev/null

# Fresh temp dir per run so state doesn't leak between invocations.
E2E_ROOT="$(mktemp -d -t macvideo-e2e-XXXXXX)"
mkdir -p "${E2E_ROOT}/music" "${E2E_ROOT}/outputs"
cp "${FIXTURES}/music/"* "${E2E_ROOT}/music/"
cp -R "${FIXTURES}/outputs/tiny-song" "${E2E_ROOT}/outputs/"
# Story 12: fresh-song fixtures for transcribe e2e (no outputs/ dirs by
# design — the test exercises the from-zero pipeline path).
cp "${FIXTURES_ROOT}/fresh-song-with-lyrics/music/"* "${E2E_ROOT}/music/"
cp "${FIXTURES_ROOT}/fresh-song-no-lyrics/music/"* "${E2E_ROOT}/music/"

cd "${REPO_ROOT}"
env \
  EDITOR_DB_PATH="${E2E_ROOT}/editor.db" \
  EDITOR_MUSIC_DIR="${E2E_ROOT}/music" \
  EDITOR_OUTPUTS_DIR="${E2E_ROOT}/outputs" \
  uv run python scripts/check_dev_environment.py --mode test >/dev/null

exec env \
  EDITOR_DB_PATH="${E2E_ROOT}/editor.db" \
  EDITOR_MUSIC_DIR="${E2E_ROOT}/music" \
  EDITOR_OUTPUTS_DIR="${E2E_ROOT}/outputs" \
  EDITOR_TEST_ENDPOINTS=1 \
  EDITOR_GENERATION_PROVIDER=fake \
  EDITOR_RENDER_PROVIDER=fake \
  uv run uvicorn editor.server.main:app --host 127.0.0.1 --port "${API_PORT}" --log-level warning
