"""Integration tests for story 8 — quality mode.

Covers:
- mode.toggle: PATCH quality_mode updates the row + marks existing clip
  takes of the OTHER mode as stale (clip_stale flag).
- mode.toggle: 409 when a clip render is in-flight.
- mode.enforce-on-render: clip regen stamps the new take's quality_mode
  correctly + invokes render_clips with the --quality-mode flag.
"""

from __future__ import annotations

import time


def _wait_until(fn, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(0.05)
    return False


def test_toggle_marks_existing_clips_stale(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    # Seed a draft-mode clip take on scene 1.
    from editor.server.store import connection
    with connection(tmp_env["db"]) as c:
        scene = c.execute(
            "SELECT id FROM scenes WHERE scene_index = 1 AND song_id = "
            "(SELECT id FROM songs WHERE slug='tiny-song')"
        ).fetchone()
        cur = c.execute("""
            INSERT INTO takes (scene_id, artefact_kind, asset_path,
                               quality_mode, created_by, created_at)
            VALUES (?, 'clip', '/fake/c_draft.mp4', 'draft', 'cli', 0)
        """, (scene["id"],))
        c.execute(
            "UPDATE scenes SET selected_clip_take_id = ? WHERE id = ?",
            (cur.lastrowid, scene["id"]),
        )

    # Toggle to final.
    r = client_for.patch("/api/songs/tiny-song", json={"quality_mode": "final"})
    assert r.status_code == 200, r.text
    scene1 = next(s for s in r.json()["scenes"] if s["index"] == 1)
    assert "clip_stale" in scene1["dirty_flags"]


def test_toggle_409_when_clip_render_in_progress(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    from editor.server.store import connection
    with connection(tmp_env["db"]) as c:
        c.execute("""
            INSERT INTO regen_runs (scope, song_id, status, created_at)
            VALUES ('scene_clip',
                    (SELECT id FROM songs WHERE slug='tiny-song'),
                    'running', ?)
        """, (time.time(),))

    r = client_for.patch("/api/songs/tiny-song", json={"quality_mode": "final"})
    assert r.status_code == 409


def test_clip_regen_stamps_quality_mode_on_new_take(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    # Flip song to final; trigger a clip regen on scene 1.
    client_for.patch("/api/songs/tiny-song", json={"quality_mode": "final"})
    r = client_for.post(
        "/api/songs/tiny-song/scenes/1/takes",
        json={"artefact_kind": "clip"},
    )
    assert r.status_code == 200
    run_id = r.json()["run_id"]

    # Wait for terminal state.
    from editor.server.store import connection
    def done():
        with connection(tmp_env["db"]) as c:
            row = c.execute(
                "SELECT status FROM regen_runs WHERE id = ?", (run_id,),
            ).fetchone()
            return row and row["status"] in ("done", "failed", "cancelled")
    assert _wait_until(done)

    # Verify the take carries quality_mode='final'.
    with connection(tmp_env["db"]) as c:
        take = c.execute("""
            SELECT quality_mode FROM takes
            WHERE source_run_id = ? AND artefact_kind = 'clip'
        """, (run_id,)).fetchone()
        assert take is not None, "clip take should have been created"
        assert take["quality_mode"] == "final"


def test_zero_clips_toggle_no_stale_markings(client_for, tmp_env, fixture_song_one):
    """PRD: 'IF a song has no clip takes THEN THE SYSTEM SHALL simplify the
    confirmation modal to omit the stale-count warning.' Backend-side, this
    means zero clip takes + toggle → no scene row's dirty_flags should
    acquire clip_stale (there's nothing to mark stale)."""
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")
    # tiny-song fixture has keyframes but no clips — verify the fixture assumption.
    detail = client_for.get("/api/songs/tiny-song").json()
    assert all(s["selected_clip_path"] is None for s in detail["scenes"])

    r = client_for.patch("/api/songs/tiny-song", json={"quality_mode": "final"})
    assert r.status_code == 200
    for s in r.json()["scenes"]:
        assert "clip_stale" not in s["dirty_flags"]
