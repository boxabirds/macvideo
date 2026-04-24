"""Unit tests for store.import — pure helpers only, no DB or filesystem."""

from __future__ import annotations

from editor.server.importer import (
    ImportReport,
    SongImportResult,
)


def test_import_report_totals_empty():
    r = ImportReport()
    assert r.total_songs == 0
    assert r.total_scenes == 0
    assert r.total_keyframe_takes == 0
    assert r.total_clip_takes == 0


def test_import_report_totals_sum_across_songs():
    r = ImportReport(songs=[
        SongImportResult(slug="a", songs_imported=1, scenes_imported=10,
                         keyframe_takes_imported=10, clip_takes_imported=5),
        SongImportResult(slug="b", songs_imported=1, scenes_imported=20,
                         keyframe_takes_imported=20, clip_takes_imported=0),
    ])
    assert r.total_songs == 2
    assert r.total_scenes == 30
    assert r.total_keyframe_takes == 30
    assert r.total_clip_takes == 5


def test_song_import_result_defaults():
    s = SongImportResult(slug="x")
    assert s.scenes_imported == 0
    assert s.warnings == []
    # Warnings is a new list per instance (no shared-mutable-default bug)
    s.warnings.append("oops")
    s2 = SongImportResult(slug="y")
    assert s2.warnings == []
