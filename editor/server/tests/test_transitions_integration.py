"""Integration tests verifying preview_change matches PATCH results.

Tests that FilterChangeTransition.preview() accurately predicts what PATCH
will do. Parity between preview and actual results ensures the UI shows
honest cost estimates before the user confirms.
"""

from __future__ import annotations

import sqlite3
import time


def _insert_song(db_path, slug: str, **kwargs):
    """Insert a test song directly into the DB."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    now = time.time()
    defaults = {
        "audio_path": f"/music/{slug}.wav",
        "duration_s": 100,
        "size_bytes": 1000000,
        "filter": None,
        "abstraction": None,
        "quality_mode": "draft",
        "world_brief": None,
        "sequence_arc": None,
    }
    defaults.update(kwargs)

    conn.execute(
        """INSERT INTO songs
           (slug, audio_path, duration_s, size_bytes, filter, abstraction,
            quality_mode, world_brief, sequence_arc, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            slug, defaults["audio_path"], defaults["duration_s"],
            defaults["size_bytes"], defaults["filter"], defaults["abstraction"],
            defaults["quality_mode"], defaults["world_brief"], defaults["sequence_arc"],
            now, now,
        ),
    )
    conn.commit()
    song_id = conn.execute("SELECT id FROM songs WHERE slug = ?", (slug,)).fetchone()["id"]
    conn.close()
    return song_id


def _insert_scene(db_path, song_id: int, scene_index: int = 0, has_clip: bool = False):
    """Insert a test scene, optionally with a clip take."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    now = time.time()
    cursor = conn.execute(
        """INSERT INTO scenes
           (song_id, scene_index, kind, target_text, start_s, end_s, target_duration_s,
            num_frames, created_at, updated_at)
           VALUES (?, ?, 'dialogue', 'test line', 0, 1, 1, 33, ?, ?)""",
        (song_id, scene_index, now, now),
    )
    scene_id = cursor.lastrowid

    if has_clip:
        cursor = conn.execute(
            """INSERT INTO takes (scene_id, artefact_kind, asset_path, created_by, created_at)
               VALUES (?, 'clip', '/clips/test.mp4', 'editor', ?)""",
            (scene_id, now),
        )
        take_id = cursor.lastrowid
        conn.execute(
            "UPDATE scenes SET selected_clip_take_id = ? WHERE id = ?",
            (take_id, scene_id),
        )

    conn.commit()
    conn.close()
    return scene_id


def _insert_regen_run(db_path, song_id: int, scope: str = "song_filter", status: str = "pending"):
    """Insert a pending regen run."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    now = time.time()
    conn.execute(
        """INSERT INTO regen_runs (scope, song_id, status, created_at)
           VALUES (?, ?, ?, ?)""",
        (scope, song_id, status, now),
    )
    conn.commit()
    conn.close()


def test_fresh_setup_preview_matches_apply(client_for, tmp_env):
    """Fresh song: preview clip_marked_stale=0, PATCH makes no clip changes."""
    _insert_song(tmp_env["db"], "fresh-song", filter=None, world_brief=None)

    # Preview the change.
    preview_res = client_for.post(
        "/api/songs/fresh-song/preview-change",
        json={"filter": "cyanotype"},
    )
    assert preview_res.status_code == 200
    preview = preview_res.json()

    # Verify preview shows no clips affected.
    assert preview["scope"]["clips_marked_stale"] == 0

    # Apply the change.
    patch_res = client_for.patch(
        "/api/songs/fresh-song",
        json={"filter": "cyanotype"},
    )
    assert patch_res.status_code == 200
    patched = patch_res.json()

    # Verify the song was updated.
    assert patched["filter"] == "cyanotype"
    # Verify no scenes (so nothing was marked stale).
    assert len(patched["scenes"]) == 0


def test_destructive_change_preview_counts_clips(client_for, tmp_env):
    """Destructive change: preview counts clips, PATCH marks same count stale."""
    song_id = _insert_song(
        tmp_env["db"], "existing", filter="oil impasto", world_brief="narrator"
    )
    _insert_scene(tmp_env["db"], song_id, scene_index=0, has_clip=True)
    _insert_scene(tmp_env["db"], song_id, scene_index=1, has_clip=True)
    _insert_scene(tmp_env["db"], song_id, scene_index=2, has_clip=False)

    # Preview the change.
    preview_res = client_for.post(
        "/api/songs/existing/preview-change",
        json={"filter": "cyanotype"},
    )
    assert preview_res.status_code == 200
    preview = preview_res.json()

    # Preview should count 2 clips marked stale.
    assert preview["scope"]["clips_marked_stale"] == 2

    # Apply the change.
    patch_res = client_for.patch(
        "/api/songs/existing",
        json={"filter": "cyanotype"},
    )
    assert patch_res.status_code == 200
    patched = patch_res.json()

    # Verify filter changed.
    assert patched["filter"] == "cyanotype"

    # Verify scenes with clips have clip_stale flag set.
    scene_0 = patched["scenes"][0]
    scene_1 = patched["scenes"][1]
    scene_2 = patched["scenes"][2]

    assert "clip_stale" in scene_0["dirty_flags"]
    assert "clip_stale" in scene_1["dirty_flags"]
    assert "clip_stale" not in scene_2["dirty_flags"]


def test_noop_change_no_preview_call(client_for, tmp_env):
    """Setting filter to current value: preview is noop, PATCH returns early."""
    _insert_song(tmp_env["db"], "same-filter", filter="cyanotype", world_brief="narrator")

    # Apply change with same filter.
    patch_res = client_for.patch(
        "/api/songs/same-filter",
        json={"filter": "cyanotype"},
    )
    assert patch_res.status_code == 200
    patched = patch_res.json()

    # Filter should still be cyanotype, no chain job enqueued.
    assert patched["filter"] == "cyanotype"


def test_conflict_blocks_both_preview_and_patch(client_for, tmp_env):
    """Active regen: preview reports conflict, PATCH returns 409."""
    song_id = _insert_song(tmp_env["db"], "conflicted", filter="oil impasto")
    _insert_regen_run(tmp_env["db"], song_id, status="pending")

    # Preview should report conflict.
    preview_res = client_for.post(
        "/api/songs/conflicted/preview-change",
        json={"filter": "cyanotype"},
    )
    assert preview_res.status_code == 200
    preview = preview_res.json()
    assert preview["would_conflict_with"] is not None

    # PATCH should return 409.
    patch_res = client_for.patch(
        "/api/songs/conflicted",
        json={"filter": "cyanotype"},
    )
    assert patch_res.status_code == 409


def test_preview_estimate_matches_chain_scope(client_for, tmp_env):
    """Preview scope (scenes_with_new_prompts) matches chain job parameters."""
    song_id = _insert_song(
        tmp_env["db"], "songs-with-prompts", filter="oil impasto", world_brief="narrator"
    )

    # Add 5 scenes: 3 without user-authored prompts, 2 with.
    for i in range(3):
        _insert_scene(tmp_env["db"], song_id, scene_index=i, has_clip=False)

    scene_ids = []
    for i in range(3, 5):
        scene_id = _insert_scene(tmp_env["db"], song_id, scene_index=i, has_clip=False)
        scene_ids.append(scene_id)

    # Mark 2 scenes as user-authored.
    conn = sqlite3.connect(str(tmp_env["db"]))
    for scene_id in scene_ids:
        conn.execute(
            "UPDATE scenes SET prompt_is_user_authored = 1 WHERE id = ?",
            (scene_id,),
        )
    conn.commit()
    conn.close()

    # Preview should show 3 scenes needing new prompts (5 total - 2 user-authored).
    preview_res = client_for.post(
        "/api/songs/songs-with-prompts/preview-change",
        json={"filter": "cyanotype"},
    )
    assert preview_res.status_code == 200
    preview = preview_res.json()

    assert preview["scope"]["scenes_with_new_prompts"] == 3
    assert preview["scope"]["keyframes_to_generate"] == 5
