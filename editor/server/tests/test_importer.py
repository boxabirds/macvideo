"""Integration tests for store.import."""

from __future__ import annotations

import json


def test_import_from_tiny_fixture(tmp_env, fixture_song_one):
    from editor.server.importer import import_all
    from editor.server.store import connection, init_db

    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    init_db(tmp_env["db"])

    report = import_all(tmp_env["db"], tmp_env["music"], tmp_env["outputs"])
    assert report.total_songs == 1
    assert report.total_scenes == 2
    assert report.total_keyframe_takes == 2
    # No clip dir → zero clip takes
    assert report.total_clip_takes == 0

    with connection(tmp_env["db"]) as c:
        row = c.execute("SELECT * FROM songs WHERE slug = 'tiny-song'").fetchone()
        assert row["filter"] == "charcoal"
        assert row["abstraction"] == 25
        assert row["world_brief"].startswith("A tiny test narrator")

        scenes = c.execute(
            "SELECT * FROM scenes WHERE song_id = ? ORDER BY scene_index",
            (row["id"],),
        ).fetchall()
        assert len(scenes) == 2
        # Prev/next rehydrated from .24fps.bak archive
        assert scenes[0]["next_link"] == "Leading into beat two"
        assert scenes[1]["prev_link"] == "Following beat one"
        assert scenes[0]["beat"] == "beat one"
        assert scenes[0]["camera_intent"] == "static hold"
        # Keyframe take auto-selected
        assert scenes[0]["selected_keyframe_take_id"] is not None


def test_import_idempotent(tmp_env, fixture_song_one):
    from editor.server.importer import import_all
    from editor.server.store import connection, init_db

    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    init_db(tmp_env["db"])

    import_all(tmp_env["db"], tmp_env["music"], tmp_env["outputs"])
    second = import_all(tmp_env["db"], tmp_env["music"], tmp_env["outputs"])

    # Second run should not duplicate scenes or takes
    assert second.total_scenes == 0
    assert second.total_keyframe_takes == 0

    with connection(tmp_env["db"]) as c:
        assert c.execute("SELECT COUNT(*) FROM scenes").fetchone()[0] == 2
        assert c.execute("SELECT COUNT(*) FROM takes").fetchone()[0] == 2


def test_import_preserves_user_authored_prompt(tmp_env, fixture_song_one):
    from editor.server.importer import import_all
    from editor.server.store import connection, init_db

    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    init_db(tmp_env["db"])
    import_all(tmp_env["db"], tmp_env["music"], tmp_env["outputs"])

    # Simulate a user edit
    with connection(tmp_env["db"]) as c:
        c.execute("UPDATE scenes SET image_prompt = ?, prompt_is_user_authored = 1 "
                  "WHERE scene_index = 1",
                  ("USER-EDITED prompt",))

    # Re-import: the CLI-side image_prompts.json would try to overwrite, but
    # the user-authored flag must protect the field.
    import_all(tmp_env["db"], tmp_env["music"], tmp_env["outputs"])
    with connection(tmp_env["db"]) as c:
        row = c.execute("SELECT image_prompt FROM scenes WHERE scene_index = 1").fetchone()
        assert row["image_prompt"] == "USER-EDITED prompt"


def test_import_missing_outputs_still_imports_song(tmp_env, fixture_song_one):
    """A song with a .wav but no outputs/<slug>/ directory still imports
    (as a song with zero scenes)."""
    import shutil
    from editor.server.importer import import_all
    from editor.server.store import connection, init_db

    fixture_song_one(tmp_env["music"], tmp_env["outputs"])
    # Remove the outputs dir entirely
    shutil.rmtree(tmp_env["outputs"] / "tiny-song")

    init_db(tmp_env["db"])
    report = import_all(tmp_env["db"], tmp_env["music"], tmp_env["outputs"])
    assert report.total_songs == 1
    assert report.total_scenes == 0

    with connection(tmp_env["db"]) as c:
        assert c.execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 1
