"""Unit tests for pure staleness functions."""

from __future__ import annotations

import pytest

from editor.server.store.staleness import (
    IDENTITY_REF_WINDOW,
    SceneFieldEdit,
    SongLevelEdit,
    TakeArrival,
    flags_after_scene_edit,
    flags_after_song_level_edit,
    flags_after_take_arrival,
)


def test_beat_edit_marks_both_artefacts_stale():
    flags, neighbours = flags_after_scene_edit(
        current_flags=[],
        edit=SceneFieldEdit(scene_index=30, field_name="beat"),
        total_scene_count=70,
    )
    assert "keyframe_stale" in flags
    assert "clip_stale" in flags
    # Identity chain: 31, 32, 33, 34
    assert set(neighbours.keys()) == {31, 32, 33, 34}
    for flags_set in neighbours.values():
        assert flags_set == {"keyframe_stale"}


def test_image_prompt_edit_does_not_ripple():
    flags, neighbours = flags_after_scene_edit(
        current_flags=[],
        edit=SceneFieldEdit(scene_index=10, field_name="image_prompt"),
        total_scene_count=70,
    )
    assert "keyframe_stale" in flags
    assert "clip_stale" in flags
    # Image prompt edits don't change the identity-chain references
    assert neighbours == {}


def test_identity_chain_stops_at_song_end():
    flags, neighbours = flags_after_scene_edit(
        current_flags=[],
        edit=SceneFieldEdit(scene_index=68, field_name="subject_focus"),
        total_scene_count=69,
    )
    # Only scene 69 remains; 70, 71, 72 don't exist
    assert set(neighbours.keys()) == {69}


def test_irrelevant_field_no_op():
    flags, neighbours = flags_after_scene_edit(
        current_flags=[],
        edit=SceneFieldEdit(scene_index=5, field_name="target_text"),
        total_scene_count=10,
    )
    assert flags == set()
    assert neighbours == {}


def test_revert_clears_local_flags():
    flags, _ = flags_after_scene_edit(
        current_flags=["keyframe_stale", "clip_stale"],
        edit=SceneFieldEdit(scene_index=5, field_name="beat",
                            reverted_to_saved=True),
        total_scene_count=10,
    )
    assert "keyframe_stale" not in flags
    assert "clip_stale" not in flags


def test_song_filter_change_marks_every_scene():
    current = {i: [] for i in range(1, 71)}
    result = flags_after_song_level_edit(current, SongLevelEdit(kind="filter"))
    assert len(result) == 70
    for flags in result.values():
        assert flags == {"keyframe_stale", "clip_stale"}


def test_take_arrival_clears_keyframe_stale_when_prompt_matches():
    flags = flags_after_take_arrival(
        current_flags=["keyframe_stale", "clip_stale"],
        arrival=TakeArrival(
            scene_index=5,
            artefact_kind="keyframe",
            prompt_snapshot="p1",
            current_image_prompt="p1",
        ),
    )
    assert "keyframe_stale" not in flags
    # clip_stale untouched — needs a separate clip take to clear
    assert "clip_stale" in flags


def test_take_arrival_does_not_clear_when_prompt_differs():
    flags = flags_after_take_arrival(
        current_flags=["keyframe_stale"],
        arrival=TakeArrival(
            scene_index=5,
            artefact_kind="keyframe",
            prompt_snapshot="OLD prompt",
            current_image_prompt="NEW prompt",
        ),
    )
    assert "keyframe_stale" in flags


def test_clip_take_arrival_clears_clip_stale_when_source_matches():
    flags = flags_after_take_arrival(
        current_flags=["clip_stale"],
        arrival=TakeArrival(
            scene_index=5,
            artefact_kind="clip",
            prompt_snapshot=None,
            current_image_prompt=None,
            source_keyframe_take_id=42,
            current_selected_keyframe_take_id=42,
        ),
    )
    assert "clip_stale" not in flags


def test_clip_take_arrival_does_not_clear_when_keyframe_changed():
    flags = flags_after_take_arrival(
        current_flags=["clip_stale"],
        arrival=TakeArrival(
            scene_index=5,
            artefact_kind="clip",
            prompt_snapshot=None,
            current_image_prompt=None,
            source_keyframe_take_id=42,
            current_selected_keyframe_take_id=99,  # user picked a different kf
        ),
    )
    assert "clip_stale" in flags


def test_window_constant_matches_identity_ref_window():
    assert IDENTITY_REF_WINDOW == 4
