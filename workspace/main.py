"""The ShiftPoint workspace: its own FastAPI app with its own world (ADR 0001).

Jmail (/mail), Jdrive (/drive), Habspot CRM (/crm), Calendario (/calendar) and quotes, over the
fictional ShiftPoint world in `world/`. Every write goes through `events.commit`, the single gate
where the monitor checks agent steps (ADR 0005).

Two ways to run it:
- On its own:  `uv run uvicorn workspace.main:app --port 8000` (its own state session).
- Mounted:     `server.py` mounts `create_app(standalone=False)` at "/" next to the monitor
               canvas, and provides the state session itself (one deploy, one state store).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import dispatch, events, session
from .routers import admin, calendar, crm, drive, mail, quotes, ui
from .state import MemoryStore, StateStore, make_store

ROUTERS = (mail.router, drive.router, crm.router, calendar.router, quotes.router, ui.router, admin.router)


def create_app(*, standalone: bool = True, state: StateStore | None = None) -> FastAPI:
    store_backend = state or make_store()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if standalone and isinstance(store_backend, MemoryStore):
            events.restore(None)  # seed the world in process memory
        yield

    ws = FastAPI(title="ShiftPoint workspace", lifespan=lifespan)
    ws.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    ui.install(ws)  # click-level page views
    if standalone:
        session.install(ws, store_backend)  # outermost: state load/save + actor

    @ws.get("/")
    def root():
        return RedirectResponse("/mail")

    for r in ROUTERS:
        ws.include_router(r)
    events.set_replayer(lambda request: dispatch.replay(ws, request))
    return ws


app = create_app()
