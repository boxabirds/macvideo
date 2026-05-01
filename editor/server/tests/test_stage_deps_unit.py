"""Unit tests for story 9's stage dependency checker.

_stage_deps(conn, song_id) computes, for each of the 5 stages, whether it's
done and whether its upstream prerequisites are met. Pure logic against DB
state — no subprocess, no Gemini, no filesystem.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from editor.server.api.stages import _stage_deps
from editor.server.store.schema import init_db


@pytest.fixture(autouse=True)
def _workflow_providers(monkeypatch):
    monkeypatch.setenv("EDITOR_GENERATION_PROVIDER", "fake")
    monkeypatch.setenv("EDITOR_RENDER_PROVIDER", "fake")


def _mk_db():
    """In-memory DB with the real schema applied."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    # Use init_db's schema by executing the DDL directly. init_db writes to
    # a file path; we reuse its statements via a temp file that we then
    # ignore — acceptable for a unit test that just needs a schema.
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        init_db(Path(td) / "tmp.db")
        # Re-run schema against the in-memory conn by copying DDL
    # Simpler: use init_db's connection directly.
    import tempfile as _tf
    td = _tf.mkdtemp()
    dbp = Path(td) / "u.db"
    init_db(dbp)
    conn.close()
    conn = sqlite3.connect(str(dbp), isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn


def _insert_song(conn, *, slug="s", filter_=None, abstraction=None,
                 world_brief=None, sequence_arc=None):
    now = time.time()
    conn.execute("""
        INSERT INTO songs (slug, audio_path, duration_s, size_bytes,
                           filter, abstraction, quality_mode,
                           world_brief, sequence_arc, created_at, updated_at)
        VALUES (?, '/x.wav', 5, 100, ?, ?, 'draft', ?, ?, ?, ?)
    """, (slug, filter_, abstraction, world_brief, sequence_arc, now, now))
    return conn.execute("SELECT id FROM songs WHERE slug = ?", (slug,)).fetchone()["id"]


def _insert_scene(conn, song_id, idx, *, beat=None, image_prompt=None,
                  kf_take_id=None):
    now = time.time()
    conn.execute("""
        INSERT INTO scenes (song_id, scene_index, kind, target_text,
                            start_s, end_s, target_duration_s, num_frames,
                            beat, image_prompt, selected_keyframe_take_id,
                            created_at, updated_at)
        VALUES (?, ?, 'lyric', 'x', 0, 1, 1, 9, ?, ?, ?, ?, ?)
    """, (song_id, idx, beat, image_prompt, kf_take_id, now, now))


def test_transcribe_done_when_song_has_scenes():
    conn = _mk_db()
    song_id = _insert_song(conn)
    _insert_scene(conn, song_id, 1)
    deps = _stage_deps(conn, song_id)
    assert deps["transcribe"]["done"] is True


def test_world_brief_ok_to_start_requires_filter_and_abstraction():
    conn = _mk_db()
    song_id = _insert_song(conn)  # filter=None, abstraction=None
    _insert_scene(conn, song_id, 1)
    deps = _stage_deps(conn, song_id)
    assert deps["world-brief"]["done"] is False
    assert deps["world-brief"]["ok_to_start"] is False

    # Now set filter + abstraction; ok_to_start flips true.
    conn.execute("UPDATE songs SET filter='charcoal', abstraction=25 WHERE id=?", (song_id,))
    deps = _stage_deps(conn, song_id)
    assert deps["world-brief"]["ok_to_start"] is True


def test_storyboard_requires_world_brief_done():
    conn = _mk_db()
    song_id = _insert_song(conn, filter_="charcoal", abstraction=25)
    _insert_scene(conn, song_id, 1)
    deps = _stage_deps(conn, song_id)
    assert deps["storyboard"]["ok_to_start"] is False

    conn.execute("UPDATE songs SET world_brief='...' WHERE id=?", (song_id,))
    deps = _stage_deps(conn, song_id)
    assert deps["storyboard"]["ok_to_start"] is True
    assert deps["storyboard"]["done"] is False

    conn.execute("UPDATE songs SET sequence_arc='...' WHERE id=?", (song_id,))
    deps = _stage_deps(conn, song_id)
    assert deps["storyboard"]["done"] is True


def test_image_prompts_done_requires_all_scenes_with_prompt():
    conn = _mk_db()
    song_id = _insert_song(conn, filter_="charcoal", abstraction=25,
                           world_brief="wb", sequence_arc="a")
    _insert_scene(conn, song_id, 1, beat="b1", image_prompt="p1")
    _insert_scene(conn, song_id, 2, beat="b2", image_prompt=None)
    deps = _stage_deps(conn, song_id)
    assert deps["image-prompts"]["done"] is False

    conn.execute("UPDATE scenes SET image_prompt='p2' WHERE song_id=? AND scene_index=2",
                 (song_id,))
    deps = _stage_deps(conn, song_id)
    assert deps["image-prompts"]["done"] is True


def test_keyframes_done_requires_every_scene_to_have_selected_take():
    conn = _mk_db()
    song_id = _insert_song(conn, filter_="charcoal", abstraction=25,
                           world_brief="wb", sequence_arc="a")
    _insert_scene(conn, song_id, 1, beat="b", image_prompt="p")
    _insert_scene(conn, song_id, 2, beat="b", image_prompt="p")
    # Neither scene has a selected keyframe take yet.
    deps = _stage_deps(conn, song_id)
    assert deps["keyframes"]["done"] is False
    assert deps["keyframes"]["ok_to_start"] is True  # with_prompt > 0

    # Insert a take + link scene 1.
    scene1 = conn.execute(
        "SELECT id FROM scenes WHERE song_id=? AND scene_index=1", (song_id,),
    ).fetchone()["id"]
    cur = conn.execute(
        "INSERT INTO takes (scene_id, artefact_kind, asset_path, created_by, created_at) "
        "VALUES (?, 'keyframe', '/x/k.png', 'cli', 0)",
        (scene1,),
    )
    conn.execute("UPDATE scenes SET selected_keyframe_take_id=? WHERE id=?",
                 (cur.lastrowid, scene1))
    deps = _stage_deps(conn, song_id)
    assert deps["keyframes"]["done"] is False  # only 1/2

    # Link scene 2.
    scene2 = conn.execute(
        "SELECT id FROM scenes WHERE song_id=? AND scene_index=2", (song_id,),
    ).fetchone()["id"]
    cur = conn.execute(
        "INSERT INTO takes (scene_id, artefact_kind, asset_path, created_by, created_at) "
        "VALUES (?, 'keyframe', '/x/k2.png', 'cli', 0)",
        (scene2,),
    )
    conn.execute("UPDATE scenes SET selected_keyframe_take_id=? WHERE id=?",
                 (cur.lastrowid, scene2))
    deps = _stage_deps(conn, song_id)
    assert deps["keyframes"]["done"] is True
