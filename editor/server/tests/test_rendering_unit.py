"""Story 28 render eligibility and recovery rules."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from editor.server.rendering import services
from editor.server.store.schema import init_db


def _db(tmp_path: Path):
    dbp = tmp_path / "render.db"
    init_db(dbp)
    conn = sqlite3.connect(str(dbp), isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _song(conn):
    now = time.time()
    cur = conn.execute(
        """
        INSERT INTO songs (
            slug, audio_path, duration_s, size_bytes, filter, abstraction,
            quality_mode, world_brief, sequence_arc, created_at, updated_at
        ) VALUES ('song', ?, 2, 100, 'charcoal', 0, 'draft', 'world', 'arc', ?, ?)
        """,
        ("/song.wav", now, now),
    )
    return cur.lastrowid


def _scene(conn, song_id: int, *, prompt: str | None = "prompt"):
    now = time.time()
    cur = conn.execute(
        """
        INSERT INTO scenes (
            song_id, scene_index, kind, target_text, start_s, end_s,
            target_duration_s, num_frames, beat, image_prompt, created_at, updated_at
        ) VALUES (?, 1, 'lyric', 'line', 0, 1, 1, 24, 'beat', ?, ?, ?)
        """,
        (song_id, prompt, now, now),
    )
    return cur.lastrowid


def test_keyframe_render_requires_image_prompt(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn)
    _scene(conn, song_id, prompt=None)

    with pytest.raises(services.RenderError) as exc:
        services.render_keyframes(conn, song_id, adapter=services.FakeRenderAdapter())

    assert exc.value.code == "image_prompt_missing"


def test_clip_render_requires_selected_keyframe(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn)
    _scene(conn, song_id)

    with pytest.raises(services.RenderError) as exc:
        services.render_clips(conn, song_id, adapter=services.FakeRenderAdapter())

    assert exc.value.code == "keyframe_missing"


def test_final_render_requires_selected_clips(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn)
    _scene(conn, song_id)

    with pytest.raises(services.RenderError) as exc:
        services.render_final_video(conn, song_id, adapter=services.FakeRenderAdapter())

    assert exc.value.code == "clip_missing"


def test_failed_keyframe_render_preserves_existing_selection(tmp_path):
    conn = _db(tmp_path)
    song_id = _song(conn)
    scene_id = _scene(conn, song_id)
    take = conn.execute(
        "INSERT INTO takes (scene_id, artefact_kind, asset_path, created_by, created_at) "
        "VALUES (?, 'keyframe', '/existing.png', 'editor', ?)",
        (scene_id, time.time()),
    )
    conn.execute("UPDATE scenes SET selected_keyframe_take_id = ? WHERE id = ?", (take.lastrowid, scene_id))

    with pytest.raises(services.RenderError):
        services.render_keyframes(
            conn, song_id,
            adapter=services.FailingRenderAdapter("fail-keyframe"),
        )

    selected = conn.execute("SELECT selected_keyframe_take_id FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    assert selected["selected_keyframe_take_id"] == take.lastrowid
