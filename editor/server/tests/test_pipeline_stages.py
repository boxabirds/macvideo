"""Integration tests for the real pipeline stage handlers.

Uses the fake_gen_keyframes.py script under tests/fake_scripts/ so we prove
the orchestration end-to-end (subprocess spawn, stdout parse, rescan-into-DB)
without making Gemini calls. The fake script emits the same stdout prefixes
and writes the same file layout as the real gen_keyframes.py, so these tests
also catch regressions in the rescan logic if the real script's output
shape changes in a future POC revision.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from editor.server.pipeline.paths import resolve_song_paths
from editor.server.pipeline.stages import run_gen_keyframes_for_stage
from editor.server.store import connection


def _fake_script() -> Path:
    here = Path(__file__).resolve().parent
    return here / "fake_scripts" / "fake_gen_keyframes.py"


def _bootstrap(tmp_env, fixture_song_one):
    """Use TestClient lifespan to create schema + import fixture."""
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


def test_world_brief_stage_writes_song_brief(tmp_env, fixture_song_one):
    """stage.world-brief runs gen_keyframes — fake writes character_brief.json;
    rescan copies brief into songs.world_brief column."""
    client = _bootstrap(tmp_env, fixture_song_one)
    try:
        # Remove any existing character_brief so the fake script writes a new one
        brief = tmp_env["outputs"] / "tiny-song" / "character_brief.json"
        if brief.exists():
            brief.unlink()

        result = run_gen_keyframes_for_stage(
            song_slug="tiny-song",
            song_filter="charcoal",
            song_abstraction=25,
            song_quality_mode="draft",
            source_run_id=1,
            stage="world-brief",
            script_path=_fake_script(),
        )
        assert result.ok, result.stderr_tail

        with connection(tmp_env["db"]) as c:
            row = c.execute("SELECT world_brief FROM songs WHERE slug='tiny-song'").fetchone()
            assert row["world_brief"], "world_brief should have been populated from character_brief.json"
            assert "charcoal" in row["world_brief"].lower()
    finally:
        client.__exit__(None, None, None)


def test_keyframes_stage_imports_new_takes_and_selects_them(tmp_env, fixture_song_one):
    client = _bootstrap(tmp_env, fixture_song_one)
    try:
        with connection(tmp_env["db"]) as c:
            c.execute(
                "UPDATE scenes SET selected_keyframe_take_id = NULL "
                "WHERE scene_index = 2 AND song_id = (SELECT id FROM songs WHERE slug='tiny-song')"
            )
        kf2 = tmp_env["outputs"] / "tiny-song" / "keyframes" / "keyframe_002.png"
        if kf2.exists():
            kf2.unlink()

        before = client.get("/api/songs/tiny-song").json()
        before_kf = sum(1 for s in before["scenes"] if s["selected_keyframe_path"])

        result = run_gen_keyframes_for_stage(
            song_slug="tiny-song",
            song_filter="charcoal",
            song_abstraction=25,
            song_quality_mode="draft",
            source_run_id=1,
            stage="keyframes",
            script_path=_fake_script(),
        )
        assert result.ok, result.stderr_tail
        assert result.new_keyframes >= 1

        after = client.get("/api/songs/tiny-song").json()
        after_kf = sum(1 for s in after["scenes"] if s["selected_keyframe_path"])
        assert after_kf > before_kf
    finally:
        client.__exit__(None, None, None)


def test_redo_deletes_cache_then_regenerates(tmp_env, fixture_song_one):
    client = _bootstrap(tmp_env, fixture_song_one)
    try:
        run_dir = tmp_env["outputs"] / "tiny-song"
        brief_path = run_dir / "character_brief.json"
        brief_path.write_text(json.dumps({
            "brief": "pre-existing brief",
            "filter": "charcoal", "abstraction": 25, "latency_s": 0,
        }))

        result = run_gen_keyframes_for_stage(
            song_slug="tiny-song",
            song_filter="charcoal",
            song_abstraction=25,
            song_quality_mode="draft",
            source_run_id=1,
            stage="world-brief",
            redo=True,
            script_path=_fake_script(),
        )
        assert result.ok
        assert "pre-existing brief" not in brief_path.read_text()
    finally:
        client.__exit__(None, None, None)


def test_missing_shots_json_returns_non_zero_without_raising(tmp_env):
    """A stage invocation on a song without shots.json returns an error result
    rather than crashing — gives the queue a chance to mark the run failed."""
    result = run_gen_keyframes_for_stage(
        song_slug="no-such-song",
        song_filter="charcoal",
        song_abstraction=25,
        song_quality_mode="draft",
        source_run_id=1,
        stage="world-brief",
        script_path=_fake_script(),
    )
    assert not result.ok
    assert "shots.json missing" in result.stderr_tail
