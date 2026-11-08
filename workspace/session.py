"""Per-request state handling for the workspace (ADRs 0003 and 0005).

For every request that touches workspace state:
1. Who's acting: `X-Actor: agent` marks the agent (scenario runner, live agent); anything else
   is a person browsing the apps.
2. What's being done: method, path and query are recorded so a paused write can be replayed.
3. The StateStore session: load the latest snapshot if another instance changed it, run the
   request, and save the snapshot only if something changed.
"""

from __future__ import annotations

from fastapi import FastAPI, Request

from . import events, store
from .state import StateStore

STATEFUL_PREFIXES = ("/api/", "/mail", "/drive", "/crm", "/calendar", "/events")
# Monitor APIs that never touch workspace state (pure checks, catalog tools, health).
STATELESS_API = ("/api/health", "/api/catalog/", "/api/catalogs")


def is_stateful(path: str) -> bool:
    return path.startswith(STATEFUL_PREFIXES) and not path.startswith(STATELESS_API)


def install(app: FastAPI, state: StateStore) -> None:
    @app.middleware("http")
    async def workspace_session(request: Request, call_next):
        path = request.url.path
        if not is_stateful(path):
            return await call_next(request)
        actor = "agent" if request.headers.get("x-actor") == "agent" else "human"
        actor_token = events.ACTOR.set(actor)
        req_token = events.CURRENT_REQUEST.set(
            {"method": request.method, "path": path, "query": request.url.query, "body": None}
        )
        store.CHANGED["v"] = False
        try:
            async with state.session(events.restore, _dump):
                return await call_next(request)
        finally:
            events.CURRENT_REQUEST.reset(req_token)
            events.ACTOR.reset(actor_token)


def _dump() -> dict | None:
    """The snapshot to persist, or None if this request changed nothing."""
    return events.snapshot() if store.CHANGED["v"] else None
