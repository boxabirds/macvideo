"""Unit tests for store.schema — pure enum + value-mapping coverage."""

from __future__ import annotations

from editor.server.store.schema import (
    ArtefactKind,
    DirtyFlag,
    QualityMode,
    RegenStatus,
)


def test_artefact_kind_enum_values():
    assert ArtefactKind.keyframe.value == "keyframe"
    assert ArtefactKind.clip.value == "clip"
    assert {m.value for m in ArtefactKind} == {"keyframe", "clip"}


def test_regen_status_enum_values():
    assert {m.value for m in RegenStatus} == {
        "pending", "running", "done", "failed", "cancelled",
    }


def test_dirty_flag_enum_values():
    assert {m.value for m in DirtyFlag} == {"keyframe_stale", "clip_stale"}


def test_quality_mode_enum_values():
    assert {m.value for m in QualityMode} == {"draft", "final"}


def test_enums_are_string_subclasses():
    # All four enums are str subclasses so they round-trip through JSON / SQL.
    assert isinstance(ArtefactKind.keyframe, str)
    assert ArtefactKind.keyframe == "keyframe"
    assert isinstance(RegenStatus.running, str)
    assert isinstance(DirtyFlag.keyframe_stale, str)
    assert isinstance(QualityMode.draft, str)
