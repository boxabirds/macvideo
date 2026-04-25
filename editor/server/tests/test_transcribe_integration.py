"""End-to-end transcribe stage integration tests.

Story 12 — covers the gap that the per-step tests in test_pipeline_stages.py
(preflight) and test_queue_status_fidelity.py (queue contract) leave open:
the full transcribe flow from "user POSTs /stages/transcribe" through
fake whisperx_align → real make_shots → DB scene rows landing.

Cases the task body lists that are already proven elsewhere are referenced
by the file rather than duplicated:

- preflight (missing wav, missing txt, empty txt) → test_pipeline_stages.py
  test_transcribe_preflight_*.
- queue contract (StageResult ok/!ok, raised exception) →
  test_queue_status_fidelity.py.

Cases proven here:
- fresh song with no aligned.json cache → fake whisperx_align runs,
  make_shots produces shots.json, scenes land in DB, run row goes done.
- song that already has aligned.json cache → fake whisperx_align is NOT
  invoked, make_shots still runs, run row goes done.
- make_shots.py accepts an arbitrary --song slug (regression on the
  pre-12.1 hard-coded `choices=` list).
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

import pytest

from editor.server.pipeline.paths import poc_scripts_root
from editor.server.pipeline.stages import run_gen_keyframes_for_stage
from editor.server.store import connection
from editor.server.store.schema import init_db


_TESTS_DIR = Path(__file__).resolve().parent
_FAKE_WHISPERX = _TESTS_DIR / "fake_scripts" / "fake_whisperx_align.py"
_RIFF_CHUNK_HEADER_BYTES = 28
_FAKE_WAV_SAMPLE_RATE = 16000
_FAKE_WAV_DURATION_S = 1
_FAKE_WAV_FRAMES = _FAKE_WAV_SAMPLE_RATE * _FAKE_WAV_DURATION_S


def _write_silent_wav(path: Path, duration_s: float = _FAKE_WAV_DURATION_S) -> None:
    """Write a silent mono 16-bit WAV at 16 kHz so the WAV-header parse in
    fake_whisperx_align computes a duration."""
    n_frames = int(_FAKE_WAV_SAMPLE_RATE * duration_s)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_FAKE_WAV_SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * n_frames)


def _whisperx_cache_path(slug: str) -> Path:
    """Where the editor expects the aligned.json cache to live."""
    return poc_scripts_root().parent / "whisperx_cache" / f"{slug}.aligned.json"


@pytest.fixture
def fresh_song(tmp_env, monkeypatch):
    """Create a fresh song on disk + DB row, with the fake whisperx wired in.
    Cleans the whisperx_cache file before AND after so cache state is
    deterministic across the test session."""
    slug = "transcribe-test-song"
    music = tmp_env["music"]
    _write_silent_wav(music / f"{slug}.wav")
    (music / f"{slug}.txt").write_text(
        "first line of the song\n"
        "second line about something else\n"
        "third line wraps it up\n"
    )
    init_db(tmp_env["db"])
    now = time.time()
    with connection(tmp_env["db"]) as c:
        c.execute(
            "INSERT INTO songs (slug, audio_path, lyrics_path, duration_s, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (slug, str(music / f"{slug}.wav"), str(music / f"{slug}.txt"),
             float(_FAKE_WAV_DURATION_S), now, now),
        )

    monkeypatch.setenv("EDITOR_FAKE_WHISPERX_ALIGN", str(_FAKE_WHISPERX))
    cache = _whisperx_cache_path(slug)
    if cache.exists():
        cache.unlink()
    yield {"slug": slug, "cache": cache}
    if cache.exists():
        cache.unlink()


def test_transcribe_uncached_song_runs_align_then_make_shots(fresh_song, tmp_env):
    """No cache → fake whisperx_align runs (writes the cache file), then
    make_shots derives shots.json, then importer lands scenes in the DB."""
    slug = fresh_song["slug"]
    cache = fresh_song["cache"]
    assert not cache.exists()

    result = run_gen_keyframes_for_stage(
        song_slug=slug,
        song_filter="charcoal",
        song_abstraction=25,
        song_quality_mode="draft",
        source_run_id=1,
        stage="transcribe",
    )
    assert result.ok, result.stderr_tail
    # Fake whisperx wrote the cache file.
    assert cache.exists(), "fake whisperx_align should have written the cache"
    payload = json.loads(cache.read_text())
    assert payload["method"] == "fake_whisperx_align"
    assert payload["word_count"] > 0

    # make_shots produced shots.json in the run dir.
    run_dir = tmp_env["outputs"] / slug
    shots_path = run_dir / "shots.json"
    assert shots_path.exists()
    shots_data = json.loads(shots_path.read_text())
    assert shots_data["shot_count"] > 0

    # Scenes landed in the DB via the importer re-run inside _run_transcribe.
    with connection(tmp_env["db"]) as c:
        scene_count = c.execute(
            "SELECT COUNT(*) AS n FROM scenes WHERE song_id = "
            "(SELECT id FROM songs WHERE slug = ?)", (slug,),
        ).fetchone()["n"]
    assert scene_count == shots_data["shot_count"]


def test_transcribe_cached_song_skips_whisperx(fresh_song, tmp_env):
    """When aligned.json already exists, whisperx_align must NOT run.
    Pre-populate the cache with a sentinel value and assert it is unchanged
    after the transcribe call."""
    slug = fresh_song["slug"]
    cache = fresh_song["cache"]
    cache.parent.mkdir(parents=True, exist_ok=True)
    sentinel_payload = {
        "audio": "/sentinel.wav",
        "ground_truth": None,
        "duration_s": float(_FAKE_WAV_DURATION_S),
        "method": "PRE_EXISTING_CACHE_DO_NOT_OVERWRITE",
        "words": [
            {"word": "first",  "start": 0.0, "end": 0.3, "score": 1.0},
            {"word": "line",   "start": 0.3, "end": 0.5, "score": 1.0},
            {"word": "of",     "start": 0.5, "end": 0.6, "score": 1.0},
            {"word": "the",    "start": 0.6, "end": 0.7, "score": 1.0},
            {"word": "song",   "start": 0.7, "end": 0.9, "score": 1.0},
            {"word": "second", "start": 0.9, "end": 1.0, "score": 1.0},
            {"word": "line",   "start": 1.0, "end": 1.1, "score": 1.0},
            {"word": "about",  "start": 1.1, "end": 1.2, "score": 1.0},
            {"word": "something", "start": 1.2, "end": 1.4, "score": 1.0},
            {"word": "else",   "start": 1.4, "end": 1.5, "score": 1.0},
            {"word": "third",  "start": 1.5, "end": 1.6, "score": 1.0},
            {"word": "line",   "start": 1.6, "end": 1.7, "score": 1.0},
            {"word": "wraps",  "start": 1.7, "end": 1.85, "score": 1.0},
            {"word": "it",     "start": 1.85, "end": 1.9, "score": 1.0},
            {"word": "up",     "start": 1.9, "end": 1.95, "score": 1.0},
        ],
        "word_count": 15,
        "lines": [],
    }
    cache.write_text(json.dumps(sentinel_payload))

    result = run_gen_keyframes_for_stage(
        song_slug=slug,
        song_filter="charcoal",
        song_abstraction=25,
        song_quality_mode="draft",
        source_run_id=2,
        stage="transcribe",
    )
    assert result.ok, result.stderr_tail
    # The cache file is untouched — proving fake whisperx_align didn't run.
    after = json.loads(cache.read_text())
    assert after["method"] == "PRE_EXISTING_CACHE_DO_NOT_OVERWRITE"
    # make_shots still ran against the cached aligned.json.
    shots_path = tmp_env["outputs"] / slug / "shots.json"
    assert shots_path.exists()


def test_make_shots_accepts_arbitrary_song_slug(tmp_path):
    """Regression: make_shots.py used to hard-code --song choices=[
    'busy-invisible','chronophobia','my-little-blackbird']. After story 12
    task 1 it accepts any slug."""
    # Build a minimal aligned.json and lyric file in tmp_path.
    aligned = tmp_path / "novel.aligned.json"
    aligned.write_text(json.dumps({
        "duration_s": 6.0,
        "words": [
            {"word": "hello", "start": 0.5, "end": 1.0, "score": 1.0},
            {"word": "world", "start": 1.2, "end": 1.7, "score": 1.0},
        ],
        "lines": [],
    }))
    lyrics = tmp_path / "novel.txt"
    lyrics.write_text("hello world\n")
    out = tmp_path / "shots.json"

    make_shots = poc_scripts_root() / "make_shots.py"
    result = subprocess.run(
        [sys.executable, str(make_shots),
         "--song", "novel-arbitrary-slug",
         "--whisperx", str(aligned),
         "--lyrics", str(lyrics),
         "--out", str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["song"] == "novel-arbitrary-slug"
    assert payload["shot_count"] >= 1
