"""Unit tests for _preflight_transcribe rule ordering.

Pure logic — no subprocess, no DB, no FastAPI. Exercises every rule in
isolation plus the documented ordering: wav-missing beats txt-missing
beats empty-txt. Boundary case (single clean line) is also pinned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from editor.server.pipeline.paths import SongPaths
from editor.server.pipeline.stages import _preflight_transcribe


def _paths(tmp_path: Path, slug: str = "x") -> SongPaths:
    """Build a SongPaths anchored on tmp_path with predictable names."""
    return SongPaths(
        run_dir=tmp_path / slug,
        music_wav=tmp_path / f"{slug}.wav",
        lyrics_txt=tmp_path / f"{slug}.txt",
        shots_json=tmp_path / slug / "shots.json",
        world_brief_json=tmp_path / slug / "character_brief.json",
        storyboard_json=tmp_path / slug / "storyboard.json",
        image_prompts_json=tmp_path / slug / "image_prompts.json",
        keyframes_dir=tmp_path / slug / "keyframes",
        clips_dir=tmp_path / slug / "clips",
    )


def test_rule_1_wav_missing(tmp_path):
    """No wav, no txt → message names the wav."""
    reason = _preflight_transcribe("foo", _paths(tmp_path, "foo"))
    assert reason is not None
    assert "foo.wav" in reason
    assert "expected" in reason


def test_rule_2_txt_missing(tmp_path):
    """Wav present, txt missing → message names the txt."""
    paths = _paths(tmp_path, "foo")
    paths.music_wav.write_bytes(b"RIFF" + b"\x00" * 28)
    reason = _preflight_transcribe("foo", paths)
    assert reason is not None
    assert "foo.txt" in reason
    assert "lyric" in reason


def test_rule_3_empty_txt_only_comments_and_section_markers(tmp_path):
    """Wav + txt present, but txt has zero recognisable lyric lines."""
    paths = _paths(tmp_path, "foo")
    paths.music_wav.write_bytes(b"RIFF" + b"\x00" * 28)
    paths.lyrics_txt.write_text(
        "# header comment\n"
        "[Verse 1]\n"
        "\n"
        "  \n"
        "[Chorus]\n",
    )
    reason = _preflight_transcribe("foo", paths)
    assert reason is not None
    assert "no recognisable lyric lines" in reason


def test_rule_4_clean_inputs_returns_none(tmp_path):
    """All present + at least one clean line → preflight passes (None)."""
    paths = _paths(tmp_path, "foo")
    paths.music_wav.write_bytes(b"RIFF" + b"\x00" * 28)
    paths.lyrics_txt.write_text("a real lyric line\nanother one\n")
    assert _preflight_transcribe("foo", paths) is None


def test_ordering_wav_missing_beats_txt_missing(tmp_path):
    """Both wav AND txt missing → wav-missing reported, not txt-missing."""
    reason = _preflight_transcribe("foo", _paths(tmp_path, "foo"))
    assert "foo.wav" in reason
    assert "foo.txt" not in reason


def test_ordering_txt_missing_beats_empty_txt(tmp_path):
    """Wav present, txt missing — empty-txt rule shouldn't fire because the
    file simply doesn't exist."""
    paths = _paths(tmp_path, "foo")
    paths.music_wav.write_bytes(b"RIFF" + b"\x00" * 28)
    reason = _preflight_transcribe("foo", paths)
    assert "foo.txt" in reason
    assert "no recognisable lyric lines" not in reason


def test_boundary_single_clean_line_passes(tmp_path):
    """Smallest valid input: exactly one clean lyric line → None."""
    paths = _paths(tmp_path, "x")
    paths.music_wav.write_bytes(b"RIFF" + b"\x00" * 28)
    paths.lyrics_txt.write_text("just one line\n")
    assert _preflight_transcribe("x", paths) is None


@pytest.mark.parametrize("slug", ["short", "with-hyphens", "song_under_score"])
def test_slug_appears_in_messages(tmp_path, slug):
    """The slug interpolation works for any reasonable slug shape."""
    reason = _preflight_transcribe(slug, _paths(tmp_path, slug))
    assert slug in reason
