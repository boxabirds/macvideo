"""Integration tests for the browser contract.

These pin down the exact JSON shape that the SongBrowser React component
consumes from GET /api/songs. A regression here would silently break the
frontend even if story 1's more permissive test_api_songs.py still passed.
"""

from __future__ import annotations


def test_list_songs_returns_stage_status_shape(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")

    r = client_for.get("/api/songs")
    assert r.status_code == 200
    songs = r.json()["songs"]
    assert len(songs) == 1
    s = songs[0]

    # The browser's TypeScript Song type depends on exactly these keys.
    for key in ("slug", "audio_path", "duration_s", "size_bytes",
                "filter", "abstraction", "quality_mode", "status"):
        assert key in s, f"missing key {key!r}"

    # StageStatus shape
    st = s["status"]
    for key in ("transcription", "world_brief", "storyboard",
                "keyframes_done", "keyframes_total",
                "clips_done", "clips_total", "final"):
        assert key in st, f"missing status key {key!r}"
    for key in ("transcription", "world_brief", "storyboard", "final"):
        assert st[key] in ("empty", "done", "error"), f"bad {key}: {st[key]!r}"
    for key in ("keyframes_done", "keyframes_total", "clips_done", "clips_total"):
        assert isinstance(st[key], int)


def test_list_songs_ordered_alphabetically(client_for, tmp_env, fixture_song_one):
    """Browser renders in a fixed order; the endpoint must sort alphabetically."""
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    # Add a second fake song
    import shutil
    from pathlib import Path
    music = tmp_env["music"]
    shutil.copy(music / "tiny-song.wav", music / "aaa-song.wav")
    (music / "aaa-song.txt").write_text("la la\n")
    client_for.post("/api/import")

    songs = client_for.get("/api/songs").json()["songs"]
    slugs = [s["slug"] for s in songs]
    assert slugs == sorted(slugs), f"expected alphabetical, got {slugs}"


def test_list_songs_quality_mode_defaults_to_draft(client_for, tmp_env, fixture_song_one):
    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    client_for.post("/api/import")
    songs = client_for.get("/api/songs").json()["songs"]
    for s in songs:
        assert s["quality_mode"] == "draft"
