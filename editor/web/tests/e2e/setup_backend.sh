#!/usr/bin/env bash
# Start the FastAPI backend against a fresh temp dir pre-populated with the
# tiny-song fixture. Playwright's webServer invokes this script; lifespan will
# auto-import the fixture on startup.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
FIXTURES_ROOT="${REPO_ROOT}/editor/server/tests/fixtures"
FIXTURES="${FIXTURES_ROOT}/tiny-song"

# Build any fixtures that are not committed (idempotent).
uv run python "${FIXTURES_ROOT}/_build_tiny_song.py" >/dev/null
uv run python "${FIXTURES_ROOT}/_build_fresh_songs.py" >/dev/null

# Clear any leftover whisperx alignment cache files for the e2e fixture
# slugs so each run exercises the fresh-cache path deterministically.
# (Cache lives at pocs/29-full-song/whisperx_cache/<slug>.aligned.json
# and persists across runs by design — test-isolation concern only.)
WHISPERX_CACHE="${REPO_ROOT}/pocs/29-full-song/whisperx_cache"
rm -f "${WHISPERX_CACHE}/fresh-song-wl.aligned.json"
rm -f "${WHISPERX_CACHE}/fresh-song-nl.aligned.json"

# Fresh temp dir per run so state doesn't leak between invocations.
E2E_ROOT="$(mktemp -d -t macvideo-e2e-XXXXXX)"
mkdir -p "${E2E_ROOT}/music" "${E2E_ROOT}/outputs"
cp "${FIXTURES}/music/"* "${E2E_ROOT}/music/"
cp -R "${FIXTURES}/outputs/tiny-song" "${E2E_ROOT}/outputs/"
# Story 12: fresh-song fixtures for transcribe e2e (no outputs/ dirs by
# design — the test exercises the from-zero pipeline path).
cp "${FIXTURES_ROOT}/fresh-song-with-lyrics/music/"* "${E2E_ROOT}/music/"
cp "${FIXTURES_ROOT}/fresh-song-no-lyrics/music/"* "${E2E_ROOT}/music/"

export EDITOR_DB_PATH="${E2E_ROOT}/editor.db"
export EDITOR_MUSIC_DIR="${E2E_ROOT}/music"
export EDITOR_OUTPUTS_DIR="${E2E_ROOT}/outputs"
# Point pipeline subprocess wrappers at the fake scripts so e2e doesn't
# call Gemini / LTX / WhisperX. Tests that explicitly exercise the real
# pipeline unset these variables.
export EDITOR_FAKE_GEN_KEYFRAMES="${REPO_ROOT}/editor/server/tests/fake_scripts/fake_gen_keyframes.py"
export EDITOR_FAKE_RENDER_CLIPS="${REPO_ROOT}/editor/server/tests/fake_scripts/fake_render_clips.py"
export EDITOR_FAKE_WHISPERX_ALIGN="${REPO_ROOT}/editor/server/tests/fake_scripts/fake_whisperx_align.py"
# Mount the test-only filesystem helper used by retry_from_failed.
export EDITOR_TEST_ENDPOINTS=1

cd "${REPO_ROOT}"
exec uv run uvicorn editor.server.main:app --port 8000 --log-level warning
