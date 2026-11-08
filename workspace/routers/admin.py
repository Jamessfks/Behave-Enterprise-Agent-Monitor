"""Run control, reset, event log, approvals and undo."""

import contextlib
import json

from fastapi import APIRouter, Request

from .. import events, store
from ..web import body, page

router = APIRouter()


@router.post("/api/admin/reset")
async def reset(request: Request):
    """Restore seed state and start a fresh run. Optional JSON: {agent, account_id, actor, label, run_id}."""
    b = {}
    with contextlib.suppress(ValueError):  # no or invalid JSON body: use defaults
        b = await request.json()
    store.reset()
    run = events.start_run(
        **{k: b[k] for k in ("agent", "account_id", "actor", "label", "run_id") if b.get(k)}
    )
    return {"ok": True, "run": run}


@router.post("/api/admin/run")
async def new_run(request: Request):
    """Start a new labelled run WITHOUT resetting data. JSON: {agent, account_id, actor, label, run_id}."""
    b = await body(request)
    run = events.start_run(
        **{k: b[k] for k in ("agent", "account_id", "actor", "label", "run_id") if b.get(k)}
    )
    return {"ok": True, "run": run}


@router.get("/api/admin/run")
def get_run():
    return {"run": events.RUN, "state": events.RUN_STATE, "pending": list(events.PENDING.keys())}


@router.get("/api/events")
def list_events(since: int = 0):
    return {"run": events.RUN, "events": events.EVENTS[since:]}


@router.post("/api/events/{event_id}/undo")
def undo(event_id: str):
    return events.undo(event_id)


@router.get("/api/approvals")
def pending():
    """Steps paused by the monitor, waiting for a person."""
    return {"pending": [{"approval_id": k, "event": v["event"]} for k, v in events.PENDING.items()]}


@router.post("/api/approvals/{approval_id}/approve")
async def approve(approval_id: str, request: Request):
    """Allow a paused step. Optional JSON {reason, by}: the reason is saved as a learned rule."""
    b = await _json(request)
    return await events.approve(approval_id, b.get("by") or "u_alex", b.get("reason") or "")


@router.post("/api/approvals/{approval_id}/reject")
async def reject(approval_id: str, request: Request):
    """Block a paused step. Optional JSON {reason, by}."""
    b = await _json(request)
    return await events.reject(approval_id, b.get("by") or "u_alex", b.get("reason") or "")


async def _json(request: Request) -> dict:
    try:
        return await request.json()
    except ValueError:
        return {}


@router.get("/api/runs/current/sources")
def run_sources():
    """Text of every object the agent read in the active run (doc bodies, email threads, deal + notes)."""
    return {"run": events.RUN, "sources": events.sources()}


@router.get("/api/rules")
def rules():
    """Written rules (policies), unwritten rules (Liam O'Connor - only the monitor sees these) and learned rules."""

    def load(p):
        d = json.loads(p.read_text()) if p.exists() else []
        return d.get("rules", []) if isinstance(d, dict) else d

    w = store.ROOT / "world" / "rules"
    return {
        "written": load(w / "written_rules.json"),
        "unwritten": load(w / "unwritten_rules.json"),
        "learned": list(events.LEARNED),
    }


@router.get("/events")
def events_page(request: Request, ui: int = 0):
    """?ui=1 also shows click-level events (page views, clicks, field changes)."""
    evs = [e for e in events.EVENTS if ui or e.get("app") != "ui"]
    return page(
        request,
        "events.html",
        active_tab="",
        evs=list(reversed(evs)),
        pending=events.PENDING,
        show_ui=ui,
    )
