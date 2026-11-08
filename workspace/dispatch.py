"""Call the workspace's own routes in-process, as the agent (ADR 0009).

The scenario runner, the live agent and approval replays all act through the same HTTP routes a
person's browser uses, so every action goes through the same gate and changes the same state. They
run inside an outer request that already holds the state session, so this dispatches straight to
the matching route and skips the app's middleware (no second lock, no second load).
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException
from starlette.routing import Match

from . import events


async def call(
    app: FastAPI,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    query: str | dict[str, Any] = "",
) -> tuple[int, Any]:
    """Run one route as the agent. Returns (status, json-or-text). Paused writes come back as
    202 and blocked ones as 403, with the gate's detail, exactly as an HTTP client would see them."""
    qs = urlencode(query) if isinstance(query, dict) else (query or "")
    payload = json.dumps(body or {}).encode()
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": qs.encode(),
        "headers": [(b"content-type", b"application/json"), (b"x-actor", b"agent")],
        "client": ("agent", 0),
        "server": ("workspace", 80),
        "app": app,
    }
    route = None
    for r in app.router.routes:
        match, child = r.matches(scope)
        if match == Match.FULL:
            scope.update(child)
            route = r
            break
    if route is None:
        return 404, {"detail": f"No route for {method} {path}"}

    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    messages: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    actor = events.ACTOR.set("agent")
    req = events.CURRENT_REQUEST.set(
        {"method": method.upper(), "path": path, "query": qs, "body": body}
    )
    try:
        # FastAPI's own middleware normally provides this exit stack; dispatch skips middleware.
        async with AsyncExitStack() as stack:
            scope["fastapi_middleware_astack"] = stack
            await route.handle(scope, receive, send)
    except HTTPException as e:
        return e.status_code, {"detail": e.detail}
    finally:
        events.CURRENT_REQUEST.reset(req)
        events.ACTOR.reset(actor)

    status = next((m["status"] for m in messages if m["type"] == "http.response.start"), 500)
    raw = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, raw.decode(errors="replace")


async def replay(app: FastAPI, request: dict[str, Any]) -> Any:
    """Re-run a recorded request (an approved, previously paused write)."""
    status, out = await call(
        app, request["method"], request["path"], request.get("body"), request.get("query", "")
    )
    if status >= 400:
        raise HTTPException(status, (out or {}).get("detail") if isinstance(out, dict) else out)
    return out
