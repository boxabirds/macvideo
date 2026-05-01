"""FastAPI entry point for the storyboard editor backend."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config as _cfg
from .api import (
    assets,
    audio_transcribe as audio_transcribe_api,
    preview_change as preview_change_api,
    regen as regen_api,
    scenes,
    songs,
    stages as stages_api,
    test_only as test_only_api,
    transcript as transcript_api,
)
from .importer import import_all
from .regen.queue import configure_queues
from .store import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(_cfg.DB_PATH)
    configure_queues(_cfg.DB_PATH)
    report = import_all(_cfg.DB_PATH, _cfg.MUSIC_DIR, _cfg.OUTPUTS_DIR)
    print(f"[editor] import: {report.total_songs} songs, "
          f"{report.total_scenes} scenes, "
          f"{report.total_keyframe_takes} keyframe takes, "
          f"{report.total_clip_takes} clip takes")
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="macvideo storyboard editor", version="0.1.0",
                  lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(songs.router, prefix="/api")
    app.include_router(scenes.router, prefix="/api")
    app.include_router(transcript_api.router, prefix="/api")
    app.include_router(preview_change_api.router, prefix="/api")
    app.include_router(regen_api.router, prefix="/api")
    app.include_router(regen_api.events_router)  # /events/regen
    app.include_router(stages_api.router, prefix="/api")
    app.include_router(audio_transcribe_api.router, prefix="/api")
    app.include_router(assets.router)
    if test_only_api.is_enabled():
        app.include_router(test_only_api.router, prefix="/api")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


app = create_app()
