"""Story 34 unit tests for lossless lyric-line formatting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from editor.server.pipeline.lyric_lines import (
    LyricLineError,
    assign_line_timings,
    fallback_scene_drafts,
    format_segments_for_scene_drafts,
    normalize_transcript,
    validate_lines_lossless,
)


SEGMENTS = [
    {"text": " first words here", "start": 10.0, "end": 16.0},
    {"text": "second phrase now", "start": 20.0, "end": 26.0},
]


@dataclass
class SequenceAdapter:
    responses: list[dict[str, Any]]
    provider: str = "test"
    model: str = "test-sequence"

    def format_lines(self, *, transcript: str) -> dict[str, Any]:
        assert transcript == "first words here second phrase now"
        return self.responses.pop(0)


def test_normalize_transcript_collapses_whitespace_only():
    assert normalize_transcript(" first\nwords\t here ") == "first words here"


def test_validate_lines_accepts_exact_transcript_after_whitespace_normalization():
    lines = [
        {"line_index": 0, "text": "first words"},
        {"line_index": 1, "text": "here second phrase now"},
    ]

    assert validate_lines_lossless(" first words here second phrase now ", lines) == [
        "first words",
        "here second phrase now",
    ]


@pytest.mark.parametrize(
    "lines",
    [
        [{"line_index": 0, "text": "first words here second phrase now extra"}],
        [{"line_index": 0, "text": "first words second phrase now"}],
        [{"line_index": 0, "text": "words first here second phrase now"}],
        [{"line_index": 1, "text": "first words here second phrase now"}],
        [{"line_index": 0, "text": ""}],
        [{"line_index": "0", "text": "first words here second phrase now"}],
    ],
)
def test_validate_lines_rejects_non_lossless_or_malformed_output(lines):
    with pytest.raises(LyricLineError):
        validate_lines_lossless("first words here second phrase now", lines)


def test_assign_line_timings_interpolates_within_source_segments():
    scenes = assign_line_timings(
        SEGMENTS,
        ["first words", "here second", "phrase now"],
    )

    assert [scene.target_text for scene in scenes] == [
        "first words",
        "here second",
        "phrase now",
    ]
    assert scenes[0].start_s == pytest.approx(10.0)
    assert scenes[0].end_s == pytest.approx(14.0)
    assert scenes[1].start_s == pytest.approx(14.0)
    assert scenes[1].end_s == pytest.approx(22.0)
    assert scenes[2].start_s == pytest.approx(22.0)
    assert scenes[2].end_s == pytest.approx(26.0)


def test_format_segments_retries_until_lossless_output():
    adapter = SequenceAdapter([
        {"lines": [{"line_index": 0, "text": "first words here changed"}]},
        {"unexpected": True},
        {"lines": [
            {"line_index": 0, "text": "first words"},
            {"line_index": 1, "text": "here second phrase now"},
        ]},
    ])

    plan = format_segments_for_scene_drafts(SEGMENTS, adapter=adapter)

    assert plan.formatted is True
    assert [attempt.ok for attempt in plan.attempts] == [False, False, True]
    assert [scene.target_text for scene in plan.scenes] == [
        "first words",
        "here second phrase now",
    ]


def test_format_segments_falls_back_after_three_invalid_attempts():
    adapter = SequenceAdapter([
        {"lines": [{"line_index": 0, "text": "first words here changed"}]},
        {"lines": [{"line_index": 0, "text": "first words here changed"}]},
        {"lines": [{"line_index": 0, "text": "first words here changed"}]},
    ])

    plan = format_segments_for_scene_drafts(SEGMENTS, adapter=adapter)

    assert plan.formatted is False
    assert [attempt.ok for attempt in plan.attempts] == [False, False, False]
    assert plan.scenes == fallback_scene_drafts(SEGMENTS)


def test_format_segments_falls_back_when_formatter_provider_is_unavailable(monkeypatch):
    monkeypatch.delenv("EDITOR_GENERATION_PROVIDER", raising=False)
    monkeypatch.delenv("EDITOR_LYRIC_LINE_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    plan = format_segments_for_scene_drafts(SEGMENTS)

    assert plan.formatted is False
    assert plan.scenes == fallback_scene_drafts(SEGMENTS)
