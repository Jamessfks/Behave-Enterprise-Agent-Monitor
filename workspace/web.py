"""Shared helpers for routers: templates, request parsing, standard JSON response."""

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

from . import events, store
from .timefmt import ftime

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def fmt_dt(ts: str | None, short: bool = True) -> str:
    if not ts:
        return ""
    try:
        d = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return ts
    if short:
        if d.date().isoformat() == store.NOW[:10]:
            return ftime(d, "%-I:%M %p")
        return ftime(d, "%b %-d")
    return ftime(d, "%a, %b %-d, %Y, %-I:%M %p")


def money(v: Any) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError, OverflowError):
        return str(v or "")


def user_name(uid: str | None) -> str:
    u = store.get("users", uid)
    return u["name"] if u else (uid or "")


def contact_name(c: dict | None) -> str:
    return f"{c.get('first_name', '')} {c.get('last_name', '')}".strip() if c else ""


templates.env.globals.update(
    fmt_dt=fmt_dt,
    ftime=ftime,
    money=money,
    user_name=user_name,
    contact_name=contact_name,
    store=store,
    RUN=events.RUN,
    folder_path=store.folder_path,
    NOW=store.NOW,
)


def page(request: Request, name: str, **ctx):
    return templates.TemplateResponse(request, name, ctx)


def ok(res: dict | None = None, redirect: str | None = None, **extra) -> dict:
    """Standard JSON response for every write endpoint."""
    out = {"ok": True, "redirect": redirect}
    if res:
        out.update(
            {
                "decision": res["decision"],
                "event_id": res["event"]["id"],
                "catalog_action": res["event"]["catalog_action"],
                "reason": res.get("reason", ""),
            }
        )
    out.update(extra)
    return out


async def body(request: Request) -> dict:
    """Accept JSON (scripts, app.js) or form posts. Records the body so a paused write can be
    replayed when a person approves it (events.CURRENT_REQUEST)."""
    ct = request.headers.get("content-type", "")
    if "application/json" in ct:
        b = await request.json()
    else:
        form = await request.form()
        b = {k: v for k, v in form.items()}
    req = events.CURRENT_REQUEST.get()
    if req is not None:
        req["body"] = b
    return b


def as_list(v: Any) -> list:
    """'a@x.com, b@y.com' or ['a', 'b'] -> list of trimmed non-empty strings."""
    if v is None:
        return []
    if isinstance(v, list):
        items = v
    else:
        items = str(v).replace(";", ",").split(",")
    return [s.strip() for s in items if s and str(s).strip()]
