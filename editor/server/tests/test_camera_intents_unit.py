"""Unit test for story 3: camera-intent vocabulary.

The frontend Storyboard's camera_intent `<select>` is populated at runtime
from /api/camera-intents (story 3 test-strategy: "camera-intent list sync
test is unit-level because it's pure constant comparison").

This test pins the 11-value vocabulary so any drift between the constant
used in scenes.py, the one documented in docs/research/, and the LTX
render_clips.py side breaks a fast unit test rather than only failing at
integration time.
"""

from __future__ import annotations

from editor.server.api.scenes import CAMERA_INTENTS


EXPECTED_VOCABULARY = [
    "static hold",
    "slow push in",
    "slow pull back",
    "pan left",
    "pan right",
    "tilt up",
    "tilt down",
    "orbit left",
    "orbit right",
    "handheld drift",
    "held on detail",
]


def test_camera_intents_is_the_canonical_11():
    assert len(CAMERA_INTENTS) == 11
    assert CAMERA_INTENTS == EXPECTED_VOCABULARY


def test_camera_intents_contains_no_duplicates():
    assert len(set(CAMERA_INTENTS)) == len(CAMERA_INTENTS)


def test_camera_intents_entries_are_non_empty_strings():
    for v in CAMERA_INTENTS:
        assert isinstance(v, str) and v, f"bad entry: {v!r}"
