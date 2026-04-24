"""Integration tests for story 10 final-render handler."""

from __future__ import annotations

from pathlib import Path

from editor.server.pipeline.final import render_final
from editor.server.store import connection


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


def test_final_render_produces_finished_row_and_keeps_output(tmp_env, fixture_song_one):
    client = _bootstrap(tmp_env, fixture_song_one)
    try:
        result = render_final(
            song_slug="tiny-song",
            song_filter="charcoal",
            song_quality_mode="draft",
            source_run_id=None,
            script_path=_fake_clips(),
        )
        assert result.ok, result.stderr_tail
        assert result.finished_path is not None
        assert result.finished_path.exists()
        assert result.scene_count == 2

        finished = client.get("/api/songs/tiny-song/finished").json()["finished"]
        assert len(finished) == 1
        assert finished[0]["scene_count"] == 2
        assert finished[0]["quality_mode"] == "draft"
    finally:
        client.__exit__(None, None, None)


def test_final_render_preserves_prior_finished_rows(tmp_env, fixture_song_one):
    client = _bootstrap(tmp_env, fixture_song_one)
    try:
        r1 = render_final(
            song_slug="tiny-song", song_filter="charcoal",
            song_quality_mode="draft", source_run_id=None,
            script_path=_fake_clips(),
        )
        assert r1.ok
        r2 = render_final(
            song_slug="tiny-song", song_filter="charcoal",
            song_quality_mode="final", source_run_id=None,
            script_path=_fake_clips(),
        )
        assert r2.ok
        finished = client.get("/api/songs/tiny-song/finished").json()["finished"]
        assert len(finished) == 2
        modes = {f["quality_mode"] for f in finished}
        assert modes == {"draft", "final"}
    finally:
        client.__exit__(None, None, None)
