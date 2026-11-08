"""Run control, reset, event log, approvals and undo."""
from fastapi import APIRouter, Request

from .. import events, store
from ..web import body, page

router = APIRouter()


@router.post("/api/admin/reset")
async def reset(request: Request):
    """Restore seed state and start a fresh run. Optional JSON: {agent, account_id, actor, label, run_id}."""
    b = {}
    try:
        b = await request.json()
    except Exception:
        pass
    store.reset()
    run = events.start_run(**{k: b[k] for k in ("agent", "account_id", "actor", "label", "run_id") if b.get(k)})
    return {"ok": True, "run": run}


@router.post("/api/admin/run")
async def new_run(request: Request):
    """Start a new labelled run WITHOUT resetting data. JSON: {agent, account_id, actor, label, run_id}."""
    b = await body(request)
    run = events.start_run(**{k: b[k] for k in ("agent", "account_id", "actor", "label", "run_id") if b.get(k)})
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


@router.post("/api/approvals/{approval_id}/approve")
def approve(approval_id: str):
    return events.approve(approval_id)


@router.post("/api/approvals/{approval_id}/reject")
def reject(approval_id: str):
    return events.reject(approval_id)


@router.get("/events")
def events_page(request: Request):
    return page(request, "events.html", active_tab="", evs=list(reversed(events.EVENTS)),
                pending=events.PENDING)
