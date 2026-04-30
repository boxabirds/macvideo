"""Story 11 integration tests for filter transition preview/apply parity."""

from __future__ import annotations

from .test_transitions_integration import (
    _insert_regen_run,
    _insert_scene,
    _insert_song,
)


def test_preview_apply_parity_fresh_setup(client_for, tmp_env):
    _insert_song(tmp_env["db"], "fresh-filter", filter=None, world_brief=None)

    preview_res = client_for.post(
        "/api/songs/fresh-filter/preview-change",
        json={"filter": "cyanotype"},
    )
    assert preview_res.status_code == 200
    preview = preview_res.json()
    assert preview["kind"] == "fresh-setup"
    assert preview["scope"]["clips_marked_stale"] == 0

    patch_res = client_for.patch(
        "/api/songs/fresh-filter",
        json={"filter": "cyanotype"},
    )
    assert patch_res.status_code == 200
    patched = patch_res.json()
    assert patched["filter"] == "cyanotype"
    assert patched["scenes"] == []

    runs = client_for.get("/api/songs/fresh-filter/regen").json()["runs"]
    assert any(r["scope"] == "song_filter" for r in runs)


def test_preview_apply_parity_destructive(client_for, tmp_env):
    song_id = _insert_song(
        tmp_env["db"],
        "destructive-filter",
        filter="oil impasto",
        world_brief="narrator",
        sequence_arc="arc",
    )
    _insert_scene(tmp_env["db"], song_id, scene_index=0, has_clip=True)
    _insert_scene(tmp_env["db"], song_id, scene_index=1, has_clip=False)

    preview_res = client_for.post(
        "/api/songs/destructive-filter/preview-change",
        json={"filter": "cyanotype"},
    )
    assert preview_res.status_code == 200
    preview = preview_res.json()
    assert preview["kind"] == "destructive"
    assert preview["scope"]["clips_marked_stale"] == 1

    patch_res = client_for.patch(
        "/api/songs/destructive-filter",
        json={"filter": "cyanotype"},
    )
    assert patch_res.status_code == 200
    patched = patch_res.json()
    assert patched["filter"] == "cyanotype"
    assert patched["world_brief"] is None
    assert patched["sequence_arc"] is None
    assert "clip_stale" in patched["scenes"][0]["dirty_flags"]
    assert "clip_stale" not in patched["scenes"][1]["dirty_flags"]


def test_apply_refuses_in_flight_chain(client_for, tmp_env):
    song_id = _insert_song(tmp_env["db"], "blocked-filter", filter="oil impasto")
    _insert_regen_run(tmp_env["db"], song_id, scope="stage_world_brief", status="running")

    preview_res = client_for.post(
        "/api/songs/blocked-filter/preview-change",
        json={"filter": "cyanotype"},
    )
    assert preview_res.status_code == 200
    assert preview_res.json()["would_conflict_with"] is not None

    patch_res = client_for.patch(
        "/api/songs/blocked-filter",
        json={"filter": "cyanotype"},
    )
    assert patch_res.status_code == 409


def test_same_filter_no_op(client_for, tmp_env):
    _insert_song(tmp_env["db"], "same-filter", filter="cyanotype")

    patch_res = client_for.patch(
        "/api/songs/same-filter",
        json={"filter": "cyanotype"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["filter"] == "cyanotype"
    runs = client_for.get("/api/songs/same-filter/regen").json()["runs"]
    assert not any(r["scope"] == "song_filter" for r in runs)


def test_unknown_song_preview_returns_404(client_for):
    res = client_for.post(
        "/api/songs/not-a-song/preview-change",
        json={"filter": "cyanotype"},
    )
    assert res.status_code == 404
