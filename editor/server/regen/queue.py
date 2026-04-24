"""In-process regen queues on a thread pool.

Uses concurrent.futures.ThreadPoolExecutor so background work is independent
of the request's event loop. That means workers make progress during
TestClient-driven tests and during ordinary uvicorn requests alike.

- keyframe_queue: 4-worker pool (Gemini-API-bound)
- clip_queue: 1-worker pool (GPU-bound; LTX serialisation)
"""

from __future__ import annotations

import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .events import RegenEvent, hub
from .runs import RegenRun, update_run_status
from ..store import connection


@dataclass
class RegenJob:
    run: RegenRun
    handler: Callable[[RegenRun], Awaitable[None]]


class _RegenQueue:
    def __init__(self, *, name: str, concurrency: int) -> None:
        self.name = name
        self.concurrency = concurrency
        self._pool = ThreadPoolExecutor(
            max_workers=concurrency, thread_name_prefix=name,
        )
        self._db_path: Optional[Path] = None

    def configure(self, db_path: Path) -> None:
        self._db_path = db_path

    def _execute(self, job: RegenJob) -> None:
        run = job.run
        if self._db_path:
            with connection(self._db_path) as conn:
                update_run_status(conn, run.id, "running")
        hub.publish(RegenEvent(
            run_id=run.id, song_id=run.song_id, scope=run.scope,
            status="running", artefact_kind=run.artefact_kind,
        ))
        try:
            # Handler is an async function; drive it with asyncio.run here
            # because each worker thread has no running loop of its own.
            asyncio.run(job.handler(run))
            if self._db_path:
                with connection(self._db_path) as conn:
                    update_run_status(conn, run.id, "done")
            hub.publish(RegenEvent(
                run_id=run.id, song_id=run.song_id, scope=run.scope,
                status="done", artefact_kind=run.artefact_kind,
            ))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            err = str(e) or type(e).__name__
            if self._db_path:
                with connection(self._db_path) as conn:
                    update_run_status(conn, run.id, "failed", error=err)
            hub.publish(RegenEvent(
                run_id=run.id, song_id=run.song_id, scope=run.scope,
                status="failed", artefact_kind=run.artefact_kind,
                error=err,
            ))

    def submit(self, job: RegenJob) -> None:
        self._pool.submit(self._execute, job)

    def shutdown(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait)


keyframe_queue = _RegenQueue(name="keyframe-queue", concurrency=4)
clip_queue = _RegenQueue(name="clip-queue", concurrency=1)


def configure_queues(db_path: Path) -> None:
    keyframe_queue.configure(db_path)
    clip_queue.configure(db_path)
