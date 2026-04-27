"""Test-only endpoints, mounted only when EDITOR_TEST_ENDPOINTS=1.

Used by the e2e harness to manipulate filesystem state from inside the
browser test (e.g. inject a lyrics file mid-test to exercise the
recover-from-failed flow). NOT mounted in production.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import config as _cfg
from ..importer import import_all


router = APIRouter()


class WriteLyricsBody(BaseModel):
    slug: str
    text: str


def is_enabled() -> bool:
    return os.environ.get("EDITOR_TEST_ENDPOINTS") == "1"


@router.post("/test-only/write-lyrics")
def write_lyrics(body: WriteLyricsBody):
    """Write music/<slug>.txt and re-import so the song picks up the file."""
    if not is_enabled():
        raise HTTPException(status_code=404, detail="not found")
    target = Path(_cfg.MUSIC_DIR) / f"{body.slug}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.text)
    import_all(_cfg.DB_PATH, _cfg.MUSIC_DIR, _cfg.OUTPUTS_DIR)
    return {"ok": True, "path": str(target)}


class ResetSongBody(BaseModel):
    slug: str


@router.post("/test-only/reset-song")
def reset_song(body: ResetSongBody):
    """Restore a song to its fresh state: delete lyrics file, scenes, regen
    runs, and the run dir. Used by Story 14's audio-transcribe spec to clean
    up after itself so subsequent tests on the same fixture see a fresh
    song."""
    if not is_enabled():
        raise HTTPException(status_code=404, detail="not found")
    lyrics = Path(_cfg.MUSIC_DIR) / f"{body.slug}.txt"
    lyrics.unlink(missing_ok=True)
    run_dir = Path(_cfg.OUTPUTS_DIR) / body.slug
    if run_dir.exists():
        import shutil
        shutil.rmtree(run_dir, ignore_errors=True)
    from ..store import connection
    with connection(_cfg.DB_PATH) as c:
        row = c.execute("SELECT id FROM songs WHERE slug = ?", (body.slug,)).fetchone()
        if row:
            sid = row["id"]
            c.execute("DELETE FROM scenes WHERE song_id = ?", (sid,))
            c.execute("DELETE FROM regen_runs WHERE song_id = ?", (sid,))
    return {"ok": True}
