"""Unit tests for product quality mode-to-dimensions mapping."""

from __future__ import annotations

from editor.server.rendering.services import QUALITY_MODE_DIMENSIONS


def test_draft_mode_is_512x320_at_24fps():
    d = QUALITY_MODE_DIMENSIONS["draft"]
    assert d == {"width": 512, "height": 320, "fps": 24}


def test_final_mode_is_1920x1088_at_30fps():
    """1088 not 1080 because LTX requires height divisible by 64."""
    d = QUALITY_MODE_DIMENSIONS["final"]
    assert d == {"width": 1920, "height": 1088, "fps": 30}


def test_both_modes_defined():
    assert set(QUALITY_MODE_DIMENSIONS.keys()) == {"draft", "final"}
