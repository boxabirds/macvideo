"""Shared fixtures for editor server tests."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


_TESTS_DIR = Path(__file__).resolve().parent
_FIXTURES_DIR = _TESTS_DIR / "fixtures"


@pytest.fixture
def tmp_env(monkeypatch):
    """A temp dir with DB path + empty music + empty outputs folders."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db_path = root / "editor.db"
        music = root / "music"
        outputs = root / "outputs"
        music.mkdir()
        outputs.mkdir()
        monkeypatch.setenv("EDITOR_DB_PATH", str(db_path))
        monkeypatch.setenv("EDITOR_MUSIC_DIR", str(music))
        monkeypatch.setenv("EDITOR_OUTPUTS_DIR", str(outputs))
        # Reload the config module so the new env vars are seen
        from importlib import reload
        import editor.server.config as cfg
        reload(cfg)
        yield {
            "db": db_path,
            "music": music,
            "outputs": outputs,
            "root": root,
        }


@pytest.fixture
def fixture_song_one():
    """Copy the minimal one-song fixture into a temp tree.

    Layout of the fixture tree:
        music/tiny-song.wav            (fake wav header, 32 bytes)
        music/tiny-song.txt            (3 lines)
        outputs/tiny-song/shots.json
        outputs/tiny-song/character_brief.json
        outputs/tiny-song/storyboard.json
        outputs/tiny-song/image_prompts.json
        outputs/tiny-song/keyframes/keyframe_001.png   (tiny png)
        outputs/tiny-song/keyframes/keyframe_002.png
        outputs/tiny-song/storyboard.json.24fps.bak    (has prev/next links)
    """
    def _populate(music_dir: Path, outputs_dir: Path):
        src = _FIXTURES_DIR / "tiny-song"
        assert src.is_dir(), (
            f"fixture dir missing: {src}. "
            "Run `editor/server/tests/fixtures/_build_tiny_song.py` to create."
        )
        # Copy audio + lyrics
        shutil.copy(src / "music" / "tiny-song.wav", music_dir / "tiny-song.wav")
        shutil.copy(src / "music" / "tiny-song.txt", music_dir / "tiny-song.txt")
        # Copy outputs tree
        shutil.copytree(src / "outputs" / "tiny-song",
                        outputs_dir / "tiny-song")

    return _populate


@pytest.fixture
def client_for(tmp_env):
    """Build a TestClient against the editor app pointed at a fresh temp env.

    Uses `with` so the lifespan startup (init_db + import) actually fires.
    """
    from fastapi.testclient import TestClient
    from importlib import reload
    import editor.server.main as m
    reload(m)
    app = m.create_app()
    with TestClient(app) as client:
        yield client
