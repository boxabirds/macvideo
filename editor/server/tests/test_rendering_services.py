"""Story 28 product rendering service integration tests."""

from __future__ import annotations

import shutil
import time
from pathlib import Path


def _prepare_render_song(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")
    shutil.rmtree(tmp_env["outputs"] / "tiny-song")
    from editor.server.store import connection
    with connection(tmp_env["db"]) as c:
        c.execute(
            """
            UPDATE scenes
            SET selected_keyframe_take_id = NULL,
                selected_clip_take_id = NULL,
                dirty_flags = '[]'
            WHERE song_id = (SELECT id FROM songs WHERE slug = 'tiny-song')
            """
        )


def _run_id(db_path, *, scope: str, scene_index: int | None = None) -> int:
    from editor.server.store import connection

    with connection(db_path) as c:
        song = c.execute("SELECT id FROM songs WHERE slug = 'tiny-song'").fetchone()
        scene_id = None
        if scene_index is not None:
            scene_id = c.execute(
                "SELECT id FROM scenes WHERE song_id = ? AND scene_index = ?",
                (song["id"], scene_index),
            ).fetchone()["id"]
        cur = c.execute(
            """
            INSERT INTO regen_runs (
                scope, song_id, scene_id, artefact_kind, status, quality_mode,
                started_at, created_at
            )
            VALUES (?, ?, ?, ?, 'running', 'draft', ?, ?)
            """,
            (
                scope, song["id"], scene_id,
                "clip" if scope == "scene_clip" else "keyframe" if scope == "scene_keyframe" else None,
                time.time(), time.time(),
            ),
        )
        return int(cur.lastrowid)


def test_product_keyframes_clips_and_final_render_from_saved_data(
    client_for, tmp_env, fixture_song_one, monkeypatch,
):
    _prepare_render_song(client_for, tmp_env, fixture_song_one)
    monkeypatch.setenv("EDITOR_RENDER_PROVIDER", "fake")
    from editor.server.rendering import run_render_stage

    keyframes = run_render_stage(
        song_slug="tiny-song",
        stage="keyframes",
        source_run_id=_run_id(tmp_env["db"], scope="stage_keyframes"),
    )
    assert keyframes.ok, keyframes.stderr_tail
    song = client_for.get("/api/songs/tiny-song").json()
    assert all(Path(scene["selected_keyframe_path"]).exists() for scene in song["scenes"])
    assert all("_product_artifacts" in scene["selected_keyframe_path"] for scene in song["scenes"])

    clips = run_render_stage(
        song_slug="tiny-song",
        stage="scene-clip",
        scene_index=1,
        source_run_id=_run_id(tmp_env["db"], scope="scene_clip", scene_index=1),
    )
    assert clips.ok, clips.stderr_tail
    clips = run_render_stage(
        song_slug="tiny-song",
        stage="scene-clip",
        scene_index=2,
        source_run_id=_run_id(tmp_env["db"], scope="scene_clip", scene_index=2),
    )
    assert clips.ok, clips.stderr_tail
    song = client_for.get("/api/songs/tiny-song").json()
    assert all(Path(scene["selected_clip_path"]).exists() for scene in song["scenes"])

    final = run_render_stage(
        song_slug="tiny-song",
        stage="final-video",
        source_run_id=_run_id(tmp_env["db"], scope="final_video"),
    )
    assert final.ok, final.stderr_tail
    finished = client_for.get("/api/songs/tiny-song/finished").json()["finished"]
    assert len(finished) == 1
    assert Path(finished[0]["file_path"]).exists()

    from editor.server.store import connection
    with connection(tmp_env["db"]) as c:
        rows = c.execute(
            "SELECT artefact_kind, provider FROM render_provenance ORDER BY id",
        ).fetchall()
    assert [r["artefact_kind"] for r in rows] == ["keyframe", "keyframe", "clip", "clip", "final_video"]
    assert {r["provider"] for r in rows} == {"fake"}


def test_render_retry_preserves_existing_selected_keyframe(
    client_for, tmp_env, fixture_song_one, monkeypatch,
):
    _prepare_render_song(client_for, tmp_env, fixture_song_one)
    monkeypatch.setenv("EDITOR_RENDER_PROVIDER", "fake")
    from editor.server.rendering import run_render_stage
    from editor.server.store import connection

    first = run_render_stage(
        song_slug="tiny-song",
        stage="scene-keyframe",
        scene_index=1,
        source_run_id=_run_id(tmp_env["db"], scope="scene_keyframe", scene_index=1),
    )
    assert first.ok, first.stderr_tail
    with connection(tmp_env["db"]) as c:
        before = c.execute(
            "SELECT selected_keyframe_take_id FROM scenes WHERE scene_index = 1",
        ).fetchone()["selected_keyframe_take_id"]

    second = run_render_stage(
        song_slug="tiny-song",
        stage="scene-keyframe",
        scene_index=1,
        source_run_id=_run_id(tmp_env["db"], scope="scene_keyframe", scene_index=1),
    )
    assert second.ok, second.stderr_tail
    with connection(tmp_env["db"]) as c:
        after = c.execute(
            "SELECT selected_keyframe_take_id FROM scenes WHERE scene_index = 1",
        ).fetchone()["selected_keyframe_take_id"]
        count = c.execute(
            "SELECT COUNT(*) FROM takes WHERE artefact_kind = 'keyframe'",
        ).fetchone()[0]

    assert after == before
    assert count >= 2


def test_final_failure_preserves_existing_finished_video(
    client_for, tmp_env, fixture_song_one, monkeypatch,
):
    _prepare_render_song(client_for, tmp_env, fixture_song_one)
    monkeypatch.setenv("EDITOR_RENDER_PROVIDER", "fake")
    from editor.server.rendering import run_render_stage

    assert run_render_stage(
        song_slug="tiny-song",
        stage="keyframes",
        source_run_id=_run_id(tmp_env["db"], scope="stage_keyframes"),
    ).ok
    assert run_render_stage(
        song_slug="tiny-song",
        stage="scene-clip",
        scene_index=1,
        source_run_id=_run_id(tmp_env["db"], scope="scene_clip", scene_index=1),
    ).ok
    assert run_render_stage(
        song_slug="tiny-song",
        stage="scene-clip",
        scene_index=2,
        source_run_id=_run_id(tmp_env["db"], scope="scene_clip", scene_index=2),
    ).ok
    assert run_render_stage(
        song_slug="tiny-song",
        stage="final-video",
        source_run_id=_run_id(tmp_env["db"], scope="final_video"),
    ).ok
    before = client_for.get("/api/songs/tiny-song/finished").json()["finished"]

    monkeypatch.setenv("EDITOR_RENDER_PROVIDER", "fail-final")
    failed = run_render_stage(
        song_slug="tiny-song",
        stage="final-video",
        source_run_id=_run_id(tmp_env["db"], scope="final_video"),
    )
    assert not failed.ok
    assert "Final video renderer failed" in failed.stderr_tail
    after = client_for.get("/api/songs/tiny-song/finished").json()["finished"]
    assert after == before
