"""SSE event hub for regen status updates.

A single in-process hub fans out events to any connected /events/regen
subscribers. Each event describes a run transition: pending → running →
done/failed/cancelled, with optional progress / error payload.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional


MAX_REPLAY = 50


@dataclass
class RegenEvent:
    run_id: int
    song_id: int
    scope: str
    status: str
    scene_index: Optional[int] = None
    artefact_kind: Optional[str] = None
    progress: Optional[int] = None   # percent or count
    total: Optional[int] = None
    error: Optional[str] = None
    seq: int = 0

    def to_sse(self) -> str:
        body = json.dumps({
            "run_id": self.run_id,
            "song_id": self.song_id,
            "scope": self.scope,
            "status": self.status,
            "scene_index": self.scene_index,
            "artefact_kind": self.artefact_kind,
            "progress": self.progress,
            "total": self.total,
            "error": self.error,
        })
        return f"id: {self.seq}\nevent: regen\ndata: {body}\n\n"


class RegenEventHub:
    """Single-writer, multi-subscriber event fan-out.

    Keeps a ring buffer of the most recent events so new subscribers can
    catch up (via Last-Event-ID).
    """

    def __init__(self, max_replay: int = MAX_REPLAY) -> None:
        self._queues: set[asyncio.Queue[RegenEvent]] = set()
        self._recent: deque[RegenEvent] = deque(maxlen=max_replay)
        self._seq = 0

    def publish(self, event: Any) -> None:
        """Accepts a RegenEvent or a dict; broadcasts to all subscribers."""
        if isinstance(event, dict):
            event = RegenEvent(**event)
        self._seq += 1
        event.seq = self._seq
        self._recent.append(event)
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Back-pressure: drop the slow subscriber.
                self._queues.discard(q)

    def history(self) -> list[RegenEvent]:
        """Snapshot of the event replay ring. Used by tests + by new
        subscribers that don't pass Last-Event-ID."""
        return list(self._recent)

    async def subscribe(self, last_event_id: Optional[int] = None) -> AsyncIterator[RegenEvent]:
        q: asyncio.Queue[RegenEvent] = asyncio.Queue(maxsize=100)
        # Replay any events newer than last_event_id
        if last_event_id is not None:
            for e in list(self._recent):
                if e.seq > last_event_id:
                    yield e
        self._queues.add(q)
        try:
            while True:
                ev = await q.get()
                yield ev
        finally:
            self._queues.discard(q)


# Process-wide singleton
hub = RegenEventHub()
