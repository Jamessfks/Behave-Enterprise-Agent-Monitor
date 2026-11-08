"""Where the workspace's state lives between requests (ADR 0003).

The workspace keeps its state in module globals (`store.DATA`, `events.RUN`, `events.EVENTS`, ...).
That's enough for one long-lived process. On Vercel, requests can land on different short-lived
instances with a read-only disk, so a `StateStore` makes the state survive:

- `MemoryStore` (default, local dev and tests): process memory *is* the state. No I/O.
- `RedisStore` (Vercel): one compressed JSON snapshot in Upstash Redis, plus a version counter.
  Each request takes a short lock, reloads the snapshot if another instance changed it, and saves
  it again if the request changed anything.

Chosen by `STATE_BACKEND` (`memory` | `redis`); `redis` is picked automatically when Upstash
credentials are present.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import secrets
import zlib
from collections.abc import AsyncIterator
from typing import Any, Protocol

SNAPSHOT_KEY = "agent-monitor:snapshot"
VERSION_KEY = "agent-monitor:version"
LOCK_KEY = "agent-monitor:lock"
LOCK_MS = 20_000


def encode(snapshot: dict[str, Any]) -> str:
    raw = json.dumps(snapshot, separators=(",", ":")).encode()
    return base64.b64encode(zlib.compress(raw, 6)).decode()


def decode(blob: str) -> dict[str, Any]:
    return json.loads(zlib.decompress(base64.b64decode(blob)))


class StateStore(Protocol):
    name: str

    def session(self, load, dump) -> contextlib.AbstractAsyncContextManager[None]:
        """Around one request: bring local state up to date, then persist it if it changed."""
        ...

    async def clear(self) -> None: ...


class MemoryStore:
    name = "memory"

    @contextlib.asynccontextmanager
    async def session(self, load, dump) -> AsyncIterator[None]:
        yield

    async def clear(self) -> None:
        return None


def _upstash_credentials() -> tuple[str, str] | None:
    for url_key, token_key in (
        ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"),
        ("KV_REST_API_URL", "KV_REST_API_TOKEN"),
    ):
        if os.environ.get(url_key) and os.environ.get(token_key):
            return os.environ[url_key], os.environ[token_key]
    return None


class RedisStore:
    """One snapshot in Upstash Redis, guarded by a lock so two instances never interleave writes."""

    name = "redis"

    def __init__(self, url: str, token: str):
        from upstash_redis.asyncio import Redis

        self.redis = Redis(url, token, allow_telemetry=False)
        self.version = -1  # what this instance last loaded or saved

    async def _acquire(self) -> str:
        import asyncio

        token = secrets.token_hex(8)
        for _ in range(100):  # up to ~10 s
            if await self.redis.set(LOCK_KEY, token, nx=True, px=LOCK_MS):
                return token
            await asyncio.sleep(0.1)
        raise TimeoutError("workspace state is locked by another request")

    async def _release(self, token: str) -> None:
        if await self.redis.get(LOCK_KEY) == token:
            await self.redis.delete(LOCK_KEY)

    @contextlib.asynccontextmanager
    async def session(self, load, dump) -> AsyncIterator[None]:
        token = await self._acquire()
        try:
            remote = int(await self.redis.get(VERSION_KEY) or 0)
            if remote != self.version:
                blob = await self.redis.get(SNAPSHOT_KEY)
                load(decode(blob) if blob else None)
                self.version = remote
            yield
            snapshot = dump()  # None when the request changed nothing
            if snapshot is not None:
                await self.redis.set(SNAPSHOT_KEY, encode(snapshot))
                self.version = int(await self.redis.incr(VERSION_KEY))
        finally:
            await self._release(token)

    async def clear(self) -> None:
        await self.redis.delete(SNAPSHOT_KEY, VERSION_KEY)
        self.version = -1


def make_store() -> StateStore:
    backend = os.environ.get("STATE_BACKEND")
    creds = _upstash_credentials()
    if backend == "redis" or (backend is None and creds):
        if not creds:
            raise RuntimeError(
                "STATE_BACKEND=redis needs UPSTASH_REDIS_REST_URL/TOKEN (or KV_REST_API_*)"
            )
        return RedisStore(*creds)
    return MemoryStore()
