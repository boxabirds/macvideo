"""Integration tests for store.schema."""

from __future__ import annotations

import sqlite3
import time

import pytest


def test_init_db_idempotent(tmp_env):
    from editor.server.store import init_db, connection

    init_db(tmp_env["db"])
    init_db(tmp_env["db"])  # should not raise

    with connection(tmp_env["db"]) as c:
        tables = {r["name"] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    for t in ("songs", "scenes", "takes", "regen_runs", "finished_videos"):
        assert t in tables


def test_foreign_keys_enforced(tmp_env):
    from editor.server.store import init_db, connection

    init_db(tmp_env["db"])
    with connection(tmp_env["db"]) as c:
        # Insert scene referencing non-existent song should fail
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(
                "INSERT INTO scenes (song_id, scene_index, kind, target_text, "
                "start_s, end_s, target_duration_s, num_frames, created_at, updated_at) "
                "VALUES (9999, 1, 'lyric', 'x', 0, 1, 1, 9, ?, ?)",
                (time.time(), time.time()),
            )


def test_unique_scene_per_song(tmp_env):
    from editor.server.store import init_db, connection

    init_db(tmp_env["db"])
    now = time.time()
    with connection(tmp_env["db"]) as c:
        c.execute(
            "INSERT INTO songs (slug, audio_path, created_at, updated_at) "
            "VALUES ('s', '/tmp/s.wav', ?, ?)", (now, now))
        song_id = c.execute("SELECT id FROM songs").fetchone()[0]
        c.execute(
            "INSERT INTO scenes (song_id, scene_index, kind, target_text, "
            "start_s, end_s, target_duration_s, num_frames, created_at, updated_at) "
            "VALUES (?, 1, 'lyric', 'x', 0, 1, 1, 9, ?, ?)",
            (song_id, now, now))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(
                "INSERT INTO scenes (song_id, scene_index, kind, target_text, "
                "start_s, end_s, target_duration_s, num_frames, created_at, updated_at) "
                "VALUES (?, 1, 'lyric', 'y', 0, 1, 1, 9, ?, ?)",
                (song_id, now, now))
