"""Async TTL cache: stale-while-revalidate, single-flight, optional disk persistence.

Why this is the speed lever: a view never waits for a provider it has already seen. A fresh entry
returns at once; an expired entry ALSO returns at once (marked "refreshing") while one background
task rebuilds it; only a key that was never built makes the caller wait - and concurrent callers
share that one build instead of hitting the provider N times.

Builders return a dict. A failing builder never raises to the caller: the last good value comes
back marked stale, or {"error": text} if there never was one. After a failure the key is not
rebuilt for RETRY_SECONDS, so a dead provider is not hammered on every request.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

RETRY_SECONDS = 60.0


@dataclass
class Entry:
    value: dict
    ts: float                    # time of the last GOOD build (0 if there never was one)
    error: str | None = None
    retry_at: float = 0.0

    @property
    def has_value(self) -> bool:
        return self.ts > 0


class Cache:
    def __init__(self, disk_dir: Path | None = None):
        self._mem: dict[str, Entry] = {}
        self._inflight: dict[str, asyncio.Future] = {}
        self._disk = disk_dir
        if disk_dir:
            disk_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- disk
    def _file(self, key: str) -> Path | None:
        if not self._disk:
            return None
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)[:80]
        return self._disk / f"{safe}-{hashlib.sha1(key.encode()).hexdigest()[:8]}.json"

    def _load_disk(self, key: str) -> Entry | None:
        path = self._file(key)
        try:
            raw = json.loads(path.read_text(encoding="utf-8")) if path else None
        except (OSError, ValueError):
            return None
        if not isinstance(raw, dict) or not isinstance(raw.get("value"), dict):
            return None
        return Entry(raw["value"], float(raw.get("ts", 0)) or 1.0)

    def _save_disk(self, key: str, entry: Entry) -> None:
        path = self._file(key)
        if not path:
            return
        try:
            path.write_text(json.dumps({"ts": entry.ts, "value": entry.value}, default=_jsonable), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            pass

    # ---------------------------------------------------------------- core
    def peek(self, key: str) -> dict | None:
        entry = self._mem.get(key)
        return entry.value if entry and entry.has_value else None

    def invalidate(self, prefix: str = "") -> None:
        for key in [k for k in self._mem if k.startswith(prefix)]:
            del self._mem[key]

    async def get(self, key: str, ttl: float, build: Callable[[], Awaitable[dict] | dict], *,
                  disk: bool = False, swr: bool = True, retry: float = RETRY_SECONDS) -> dict:
        entry = self._mem.get(key)
        if entry is None and disk:
            entry = self._load_disk(key)
            if entry:
                self._mem[key] = entry
        now = time.time()
        if entry:
            if entry.has_value and not entry.error and now - entry.ts < ttl:
                return _decorate(entry, refreshing=False)
            may_retry = now >= entry.retry_at
            if not entry.has_value and not may_retry:
                return {"error": entry.error or "unavailable"}
            if entry.has_value and (swr or not may_retry):
                if may_retry and key not in self._inflight:
                    self._start(key, build, disk, retry)
                return _decorate(entry, refreshing=key in self._inflight, expired=True)
        fut = self._inflight.get(key) or self._start(key, build, disk, retry)
        await asyncio.shield(fut)
        entry = self._mem[key]
        if not entry.has_value:
            return {"error": entry.error or "unavailable"}
        return _decorate(entry, refreshing=False)

    def _start(self, key: str, build, disk: bool, retry: float = RETRY_SECONDS) -> asyncio.Future:
        fut = asyncio.ensure_future(self._run(key, build, disk, retry))
        self._inflight[key] = fut
        fut.add_done_callback(lambda _f: self._inflight.pop(key, None))
        return fut

    async def _run(self, key: str, build, disk: bool, retry: float = RETRY_SECONDS) -> None:
        try:
            if inspect.iscoroutinefunction(build):
                value = await build()
            else:
                value = await asyncio.to_thread(build)
            if not isinstance(value, dict):
                raise TypeError(f"builder for {key} returned {type(value).__name__}, expected dict")
            if "error" in value:
                raise RuntimeError(value["error"])
        except Exception as exc:  # provider down, parse change, timeout - never propagate
            message = f"{type(exc).__name__}: {exc}" if not isinstance(exc, RuntimeError) else str(exc)
            old = self._mem.get(key)
            if old and old.has_value:
                self._mem[key] = Entry(old.value, old.ts, error=message, retry_at=time.time() + retry)
            else:
                self._mem[key] = Entry({}, 0.0, error=message, retry_at=time.time() + retry)
            return
        entry = Entry(value, time.time())
        self._mem[key] = entry
        if disk:
            await asyncio.to_thread(self._save_disk, key, entry)


def _decorate(entry: Entry, *, refreshing: bool, expired: bool = False) -> dict:
    out = dict(entry.value)
    out["asof"] = entry.ts
    if expired or entry.error:
        out["stale"] = True
    if entry.error:
        out["stale_reason"] = entry.error
    if refreshing:
        out["refreshing"] = True
    return out


def _jsonable(obj):
    try:
        return float(obj)
    except (TypeError, ValueError):
        return str(obj)
