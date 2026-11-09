"""Jcal: a small Google-Calendar-like week view for Alex's meetings.

Reads are logged via events.log_read, every write goes through events.commit
(create/update/delete are irreversible: invites go out to attendees).
"""

import copy
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request

from .. import events, store
from ..timefmt import ftime
from ..web import as_list, body, ok, page

router = APIRouter()

COLL = "calendar"
TZ = "-07:00"
HOURS = list(range(7, 20))  # 7:00 .. 19:00 rows
HOUR_PX = 48


# ---------------------------------------------------------------- helpers


def _events() -> list[dict]:
    return store.DATA.setdefault(COLL, [])


def _event(ev_id: str) -> dict:
    for e in _events():
        if e.get("id") == ev_id:
            return e
    raise HTTPException(404, "Event not found")


def _today() -> date:
    return date.fromisoformat(store.NOW[:10])


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _parse_day(s: str | None) -> date:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return _today()


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _in_range(e: dict, start: date, end: date) -> bool:
    d = e["start"][:10]
    return start.isoformat() <= d < end.isoformat()


def _recipients(attendees: list[dict]) -> list[str]:
    return [
        a["email"] for a in attendees if a.get("email") and a["email"].lower() != store.MY_EMAIL
    ]


def _attendees(raw) -> list[dict]:
    out = [{"name": "Alex Chen", "email": store.MY_EMAIL}]
    for x in raw if isinstance(raw, list) else as_list(raw):
        email = (x.get("email") if isinstance(x, dict) else str(x)).strip()
        if not email or email.lower() == store.MY_EMAIL:
            continue
        name = x.get("name") if isinstance(x, dict) else None
        if not name:
            c = store.contact_by_email(email) if store.DATA.get("contacts") is not None else None
            u = store.user_by_email(email) if store.DATA.get("users") is not None else None
            if c:
                name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
            elif u:
                name = u["name"]
            else:
                name = email
        out.append({"name": name, "email": email})
    return out


def _iso(day: str, hm: str) -> str:
    if not day or not hm:
        raise HTTPException(400, "Date and time are required")
    try:
        return datetime.fromisoformat(f"{day}T{hm[:5]}:00{TZ}").isoformat()
    except ValueError:
        raise HTTPException(400, f"Invalid date/time: {day} {hm}")


def _times(b: dict) -> tuple[str, str]:
    """Accept either full ISO start/end, or date + start/end (HH:MM) from the form."""
    start, end = b.get("start") or "", b.get("end") or ""
    if b.get("date"):
        start, end = _iso(b["date"], start), _iso(b["date"], end)
    for v in (start, end):
        try:
            _dt(v)
        except (TypeError, ValueError) as e:
            raise HTTPException(400, f"Invalid date/time: {v}") from e
    if _dt(end) <= _dt(start):
        raise HTTPException(400, "End must be after start")
    return start, end


def _account_of_deal(deal_id: str | None) -> str | None:
    d = store.get("deals", deal_id) if deal_id and store.DATA.get("deals") is not None else None
    if d and d.get("company_id"):
        return d["company_id"].removeprefix("co_")
    return None


def _layout(e: dict) -> dict:
    """Position of an event block in the week grid."""
    s, en = _dt(e["start"]), _dt(e["end"])
    top = max(0.0, (s.hour + s.minute / 60 - HOURS[0])) * HOUR_PX
    dur = max(0.5, (en - s).total_seconds() / 3600)
    return {
        "e": e,
        "top": int(top),
        "height": max(22, int(dur * HOUR_PX) - 2),
        "time": f"{ftime(s, '%-I:%M')} – {ftime(en, '%-I:%M %p')}",
    }


def _deals():
    return sorted(store.DATA.get("deals") or [], key=lambda d: d.get("name") or "")


def _ctx(**kw):
    kw.setdefault("active_tab", "calendar")
    kw.setdefault("HOURS", HOURS)
    kw.setdefault("HOUR_PX", HOUR_PX)
    return kw


# ---------------------------------------------------------------- pages


@router.get("/calendar")
def week_page(request: Request, week: str | None = None):
    mon = _monday(_parse_day(week) if week else _today())
    events.log_read("calendar", "calendar.open_week", "event", f"week:{mon.isoformat()}")
    days = []
    for i in range(7):
        d = mon + timedelta(days=i)
        evs = sorted(
            [e for e in _events() if e["start"][:10] == d.isoformat()], key=lambda e: e["start"]
        )
        days.append({"date": d, "is_today": d == _today(), "events": [_layout(e) for e in evs]})
    return page(
        request,
        "calendar/week.html",
        **_ctx(
            mon=mon,
            days=days,
            prev=(mon - timedelta(days=7)).isoformat(),
            next=(mon + timedelta(days=7)).isoformat(),
            today=_monday(_today()).isoformat(),
            title_range=f"{ftime(mon, '%b %-d')} – {ftime(mon + timedelta(days=6), '%b %-d, %Y')}",
        ),
    )


@router.get("/calendar/new")
def new_page(request: Request, date: str = "", time: str = "10:00"):
    d = date or store.NOW[:10]
    t = time or "10:00"
    try:
        end = (datetime.fromisoformat(f"{d}T{t[:5]}") + timedelta(minutes=30)).strftime("%H:%M")
    except ValueError:
        end = "10:30"
    form = {
        "title": "",
        "date": d,
        "start": t[:5],
        "end": end,
        "attendees": "",
        "description": "",
        "deal": "",
    }
    return page(
        request,
        "calendar/form.html",
        **_ctx(form=form, ev=None, deals=_deals(), api="/api/calendar/create"),
    )


@router.get("/calendar/event/{ev_id}")
def event_page(request: Request, ev_id: str):
    e = _event(ev_id)
    events.log_read("calendar", "calendar.open_event", "event", ev_id)
    s, en = _dt(e["start"]), _dt(e["end"])
    return page(
        request,
        "calendar/event.html",
        **_ctx(
            e=e,
            when=f"{ftime(s, '%A, %B %-d, %Y')} · {ftime(s, '%-I:%M')} – {ftime(en, '%-I:%M %p')}",
            week=_monday(s.date()).isoformat(),
            deal=store.get("deals", e.get("deal")) if store.DATA.get("deals") is not None else None,
        ),
    )


@router.get("/calendar/event/{ev_id}/edit")
def edit_page(request: Request, ev_id: str):
    e = _event(ev_id)
    events.log_read("calendar", "calendar.open_event", "event", ev_id)
    form = {
        "title": e["title"],
        "date": e["start"][:10],
        "start": e["start"][11:16],
        "end": e["end"][11:16],
        "attendees": ", ".join(_recipients(e.get("attendees") or [])),
        "description": e.get("description") or "",
        "deal": e.get("deal") or "",
    }
    return page(
        request,
        "calendar/form.html",
        **_ctx(form=form, ev=e, deals=_deals(), api=f"/api/calendar/event/{ev_id}/update"),
    )


# ---------------------------------------------------------------- JSON API


@router.get("/api/calendar/events")
def api_events(request: Request):
    q = request.query_params
    start = _parse_day(q.get("from")) if q.get("from") else _monday(_today())
    end = _parse_day(q.get("to")) + timedelta(days=1) if q.get("to") else start + timedelta(days=7)
    events.log_read(
        "calendar",
        "calendar.open_week",
        "event",
        f"week:{start.isoformat()}",
        args={"from": start.isoformat(), "to": (end - timedelta(days=1)).isoformat()},
    )
    rows = sorted([e for e in _events() if _in_range(e, start, end)], key=lambda e: e["start"])
    return {"events": rows}


@router.get("/api/calendar/event/{ev_id}")
def api_event(ev_id: str):
    e = _event(ev_id)
    events.log_read("calendar", "calendar.open_event", "event", ev_id)
    return e


@router.post("/api/calendar/create")
async def api_create(request: Request):
    b = await body(request)
    title = (b.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "Title is required")
    start, end = _times(b)
    att = _attendees(b.get("attendees"))
    deal = b.get("deal") or None
    ev_id = store.new_id("ev_cal")
    obj = {
        "id": ev_id,
        "title": title,
        "start": start,
        "end": end,
        "attendees": att,
        "location": b.get("location") or "Video call",
        "description": b.get("description") or "",
        "account": b.get("account") or _account_of_deal(deal),
        "deal": deal,
        "organizer": store.MY_EMAIL,
        "created_at": store.now_iso(),
    }
    args = {"title": title, "start": start, "end": end, "attendees": _recipients(att), "deal": deal}
    ctx = {"recipient": events.recipients_class(_recipients(att))}
    res = events.commit(
        "calendar",
        "calendar.create",
        "event",
        ev_id,
        args,
        ctx,
        lambda: _events().append(obj) or obj,
        irreversible=True,
    )
    return ok(res, redirect=f"/calendar/event/{ev_id}", id=ev_id)


@router.post("/api/calendar/event/{ev_id}/update")
async def api_update(ev_id: str, request: Request):
    e = _event(ev_id)
    b = await body(request)
    new = copy.deepcopy(e)
    if "title" in b:
        new["title"] = (b.get("title") or "").strip() or e["title"]
    if b.get("start") or b.get("end") or b.get("date"):
        merged = {
            "start": b.get("start") or (e["start"][11:16] if b.get("date") else e["start"]),
            "end": b.get("end") or (e["end"][11:16] if b.get("date") else e["end"]),
            "date": b.get("date"),
        }
        new["start"], new["end"] = _times(merged)
    if "attendees" in b:
        new["attendees"] = _attendees(b.get("attendees"))
    for k in ("description", "location"):
        if k in b:
            new[k] = b.get(k) or ""
    if "deal" in b:
        new["deal"] = b.get("deal") or None
        new["account"] = _account_of_deal(new["deal"]) or (
            e.get("account") if new["deal"] == e.get("deal") else None
        )
    new["updated_at"] = store.now_iso()
    change = "time_moved" if new["start"] != e["start"] else "details"
    rcpt = _recipients(new["attendees"])
    args = {k: new[k] for k in ("title", "start", "end", "deal")}
    args["attendees"] = rcpt
    ctx = {"recipient": events.recipients_class(rcpt), "change": change}

    def apply():
        store.replace(COLL, new)
        return new

    res = events.commit(
        "calendar", "calendar.update", "event", ev_id, args, ctx, apply, irreversible=True
    )
    return ok(res, redirect=f"/calendar/event/{ev_id}")


@router.post("/api/calendar/event/{ev_id}/delete")
async def api_delete(ev_id: str, request: Request):
    e = _event(ev_id)
    rcpt = _recipients(e.get("attendees") or [])
    ctx = {"recipient": events.recipients_class(rcpt)}
    week = _monday(_dt(e["start"]).date()).isoformat()
    res = events.commit(
        "calendar",
        "calendar.delete",
        "event",
        ev_id,
        {"title": e["title"], "start": e["start"], "attendees": rcpt},
        ctx,
        lambda: store.remove(COLL, ev_id),
        irreversible=True,
    )
    return ok(res, redirect=f"/calendar?week={week}")
