"""In-process event bus for push updates (alerts, headlines, calendar warnings, releases).

The browser holds one Server-Sent-Events connection (/api/stream). Every publish() reaches all
open tabs immediately; a reconnecting tab passes the last id it saw and receives what it missed
from a short backlog. Nothing here blocks: a slow tab loses events instead of slowing the rest.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import time
from collections import deque
from typing import AsyncIterator


class Broker:
    def __init__(self, backlog: int = 300):
        self._subs: set[asyncio.Queue] = set()
        self._recent: deque[dict] = deque(maxlen=backlog)
        self._ids = itertools.count(1)

    def publish(self, kind: str, payload: dict) -> dict:
        event = {"id": next(self._ids), "kind": kind, "ts": time.time(), **payload}
        self._recent.append(event)
        for queue in list(self._subs):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        return event

    def recent(self, kind: str | None = None, limit: int = 50) -> list[dict]:
        items = [e for e in self._recent if kind is None or e["kind"] == kind]
        return items[-limit:]

    async def stream(self, since: int = 0, heartbeat: float = 15.0) -> AsyncIterator[str]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs.add(queue)
        try:
            for event in list(self._recent):
                if event["id"] > since:
                    yield _sse(event)
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(event)
        finally:
            self._subs.discard(queue)


def _sse(event: dict) -> str:
    return f"id: {event['id']}\nevent: {event['kind']}\ndata: {json.dumps(event, default=str)}\n\n"
