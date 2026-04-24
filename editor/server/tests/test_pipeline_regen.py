"""Integration tests for per-scene regen handlers (story 5)."""

from __future__ import annotations

from pathlib import Path

from editor.server.pipeline.regen import (
    regenerate_scene_clip,
    regenerate_scene_keyframe,
)
from editor.server.store import connection


def _fake_gen() -> Path:
    return Path(__file__).resolve().parent / "fake_scripts" / "fake_gen_keyframes.py"


def _fake_clips() -> Path:
    return Path(__file__).resolve().parent / "fake_scripts" / "fake_render_clips.py"


def _bootstrap(tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    from fastapi.testclient import TestClient
    from importlib import reload
    import editor.server.main as m
    reload(m)
    app = m.create_app()
    client = TestClient(app)
    client.__enter__()
    client.post("/api/import")
    return client


def test_regen_keyframe_creates_new_take_preserves_prior(tmp_env, fixture_song_one):
    client = _bootstrap(tmp_env, fixture_song_one)
    try:
        # Count takes for scene 1 before regen
        with connection(tmp_env["db"]) as c:
            scene_id = c.execute(
                "SELECT s.id FROM scenes s JOIN songs g ON g.id = s.song_id "
                "WHERE g.slug='tiny-song' AND s.scene_index = 1"
            ).fetchone()["id"]
            before = c.execute(
                "SELECT COUNT(*) AS n FROM takes WHERE scene_id = ? "
                "AND artefact_kind = 'keyframe'", (scene_id,),
            ).fetchone()["n"]

        result = regenerate_scene_keyframe(
            song_slug="tiny-song", scene_index=1,
            song_filter="charcoal", song_abstraction=25,
            song_quality_mode="draft", source_run_id=1,
            script_path=_fake_gen(),
        )
        assert result.ok, result.stderr_tail
        assert result.new_takes == 1

        with connection(tmp_env["db"]) as c:
            after = c.execute(
                "SELECT COUNT(*) AS n FROM takes WHERE scene_id = ? "
                "AND artefact_kind = 'keyframe'", (scene_id,),
            ).fetchone()["n"]
        assert after == before + 1
    finally:
        client.__exit__(None, None, None)


def test_regen_clip_appends_new_take(tmp_env, fixture_song_one):
    client = _bootstrap(tmp_env, fixture_song_one)
    try:
        result = regenerate_scene_clip(
            song_slug="tiny-song", scene_index=1,
            song_filter="charcoal", song_quality_mode="draft",
            source_run_id=2,
            script_path=_fake_clips(),
        )
        assert result.ok, result.stderr_tail
        assert result.new_takes == 1

        # Verify a clip take exists for scene 1
        scene = client.get("/api/songs/tiny-song/scenes/1").json()
        assert scene["selected_clip_path"] is not None
    finally:
        client.__exit__(None, None, None)


def test_regen_preserves_user_pinned_selection(tmp_env, fixture_song_one):
    """regen.takes PRD clause: a regen MUST NOT change the selected take
    pointer if the user has pinned it (selection_pinned=1). Prior takes
    remain pointed-at; new take is appended but not selected."""
    client = _bootstrap(tmp_env, fixture_song_one)
    try:
        # Pin scene 1's current take.
        with connection(tmp_env["db"]) as c:
            c.execute(
                "UPDATE scenes SET selection_pinned = 1 WHERE scene_index = 1 "
                "AND song_id = (SELECT id FROM songs WHERE slug='tiny-song')"
            )
            pinned_take_id = c.execute(
                "SELECT selected_keyframe_take_id FROM scenes s "
                "JOIN songs g ON g.id = s.song_id WHERE g.slug='tiny-song' AND s.scene_index=1"
            ).fetchone()["selected_keyframe_take_id"]

        result = regenerate_scene_keyframe(
            song_slug="tiny-song", scene_index=1,
            song_filter="charcoal", song_abstraction=25,
            song_quality_mode="draft", source_run_id=7,
            script_path=_fake_gen(),
        )
        assert result.ok
        assert result.new_takes == 1

        # Pointer should still be the pinned take despite a new take existing.
        with connection(tmp_env["db"]) as c:
            after = c.execute(
                "SELECT selected_keyframe_take_id FROM scenes s "
                "JOIN songs g ON g.id = s.song_id WHERE g.slug='tiny-song' AND s.scene_index=1"
            ).fetchone()["selected_keyframe_take_id"]
            assert after == pinned_take_id
    finally:
        client.__exit__(None, None, None)


def test_regen_keyframe_only_touches_target_scene(tmp_env, fixture_song_one):
    """Regenerating scene 1's keyframe must not create a new take for scene 2
    since its keyframe file still exists (gen_keyframes skips)."""
    client = _bootstrap(tmp_env, fixture_song_one)
    try:
        with connection(tmp_env["db"]) as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM takes t JOIN scenes s ON s.id = t.scene_id "
                "JOIN songs g ON g.id = s.song_id "
                "WHERE g.slug='tiny-song' AND s.scene_index = 2 "
                "AND t.artefact_kind = 'keyframe'"
            ).fetchone()
            before_scene2 = row["n"]

        result = regenerate_scene_keyframe(
            song_slug="tiny-song", scene_index=1,
            song_filter="charcoal", song_abstraction=25,
            song_quality_mode="draft", source_run_id=1,
            script_path=_fake_gen(),
        )
        assert result.ok

        with connection(tmp_env["db"]) as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM takes t JOIN scenes s ON s.id = t.scene_id "
                "JOIN songs g ON g.id = s.song_id "
                "WHERE g.slug='tiny-song' AND s.scene_index = 2 "
                "AND t.artefact_kind = 'keyframe'"
            ).fetchone()
            assert row["n"] == before_scene2
    finally:
        client.__exit__(None, None, None)
