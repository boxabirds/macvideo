"""Unit tests for story 8 — quality mode-to-dimensions mapping.

Pure constants lookup; no DB, no subprocess. Pins the draft/final
dimensions used by render_clips.py so regressions in the mapping
are caught in milliseconds.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_render_clips_module():
    """Load render_clips.py as a module object without running its main()."""
    p = Path(__file__).resolve().parents[3] / "pocs" / "29-full-song" / "scripts" / "render_clips.py"
    spec = importlib.util.spec_from_file_location("render_clips_poc", p)
    mod = importlib.util.module_from_spec(spec)
    # Only access constants; do NOT execute main() which would try to read
    # CLI args. The module-level execution IS needed for the constants so
    # we just exec() it directly.
    spec.loader.exec_module(mod)
    return mod


def test_draft_mode_is_512x320_at_24fps():
    rc = _load_render_clips_module()
    d = rc.MODE_DIMENSIONS["draft"]
    assert d == {"width": 512, "height": 320, "fps": 24}


def test_final_mode_is_1920x1088_at_30fps():
    """1088 not 1080 because LTX requires height divisible by 64."""
    rc = _load_render_clips_module()
    d = rc.MODE_DIMENSIONS["final"]
    assert d == {"width": 1920, "height": 1088, "fps": 30}


def test_both_modes_defined():
    rc = _load_render_clips_module()
    assert set(rc.MODE_DIMENSIONS.keys()) == {"draft", "final"}


def test_legacy_constants_match_final_mode():
    """Pre-existing CLI behaviour (without --quality-mode) uses the legacy
    constants; they must match the final-mode dimensions so no behaviour
    changed for users invoking the script the old way."""
    rc = _load_render_clips_module()
    assert rc.WIDTH == rc.MODE_DIMENSIONS["final"]["width"]
    assert rc.HEIGHT == rc.MODE_DIMENSIONS["final"]["height"]
    assert rc.FPS == rc.MODE_DIMENSIONS["final"]["fps"]
