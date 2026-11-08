"""What one step changed in the workspace, field by field.

`capture()` copies the world before a write; `diff(before, after)` compares it with the world
after and describes each change the way a person would look for it in the apps:
- which app and which page shows it (`url`);
- what to point at on that page (`focus`: CSS selectors that the templates mark with
  `data-field`, `data-thread-id`, `data-doc-id`, `data-event-id` or an element id);
- each field's value before and after, formatted as the apps show it.

The canvas uses this to show a step's before and after (docs/workspace.md). It only reads the
world; it never changes it.
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from . import store

COLLS = ("deals", "contacts", "companies", "activities", "threads", "docs", "calendar")
APP = {
    "deals": "Habspot",
    "contacts": "Habspot",
    "companies": "Habspot",
    "activities": "Habspot",
    "threads": "Jmail",
    "docs": "Jdrive",
    "calendar": "Calendario",
}
# Bookkeeping fields nobody looks for in the apps.
NOISE = {"updated_at", "created_at", "edited_at", "ts", "unread", "organizer", "id"}
LABELS = {
    "close_date": "Close date",
    "next_step": "Next step",
    "next_step_date": "Next step date",
    "discount_pct": "Discount",
    "contact_ids": "Contacts",
    "start": "When",
    "attendees": "Guests",
    "folder_id": "Folder",
    "shared_with": "Shared with",
    "first_name": "First name",
    "body": "Text",
    "last_name": "Last name",
}
STAGES = {
    "new": "New",
    "discovery": "Discovery",
    "demo": "Demo",
    "proposal": "Proposal",
    "negotiation": "Negotiation",
    "closed_won": "Closed Won",
    "closed_lost": "Closed Lost",
}
BODY_CHARS = 280


def capture() -> dict[str, list[dict[str, Any]]]:
    """A copy of the parts of the world a step can change."""
    return {c: copy.deepcopy(store.DATA.get(c, [])) for c in COLLS}


def diff(before: dict[str, list[dict[str, Any]]], after: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for coll in COLLS:
        old = {o["id"]: o for o in before.get(coll, []) if "id" in o}
        new = {o["id"]: o for o in after.get(coll, []) if "id" in o}
        for oid, obj in new.items():
            if oid not in old:
                out.append(_created(coll, obj))
            elif obj != old[oid]:
                ch = _updated(coll, old[oid], obj)
                if ch:
                    out.append(ch)
        for oid, obj in old.items():
            if oid not in new:
                out.append(_change(coll, obj, "deleted", []))
    return out


# ---------- one change ----------


def _created(coll: str, obj: dict[str, Any]) -> dict[str, Any]:
    if coll == "threads":
        msgs = obj.get("messages") or []
        kind = "drafted" if "DRAFT" in (obj.get("labels") or []) else "sent"
        return _message_change(obj, msgs[-1] if msgs else {}, kind)
    fields = [
        _field(coll, k, None, v)
        for k, v in obj.items()
        if k not in NOISE
        and _shown(coll, k)
        and v not in (None, "", [], {})
        and not (coll == "activities" and k == "title" and v == "Note")
    ]
    return _change(coll, obj, "created", fields)


def _updated(coll: str, old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any] | None:
    if coll == "threads":
        seen = {m.get("id") for m in old.get("messages") or []}
        added = [m for m in new.get("messages") or [] if m.get("id") not in seen]
        if added:
            kind = "drafted" if "DRAFT" in (new.get("labels") or []) else "sent"
            return _message_change(new, added[-1], kind)
    fields = [
        f
        for k in dict.fromkeys([*old, *new])
        if k not in NOISE and _shown(coll, k) and old.get(k) != new.get(k)
        for f in [_field(coll, k, old.get(k), new.get(k))]
        if f["before"] != f["after"]  # e.g. an offer's internal status: nothing a person sees
    ]
    return _change(coll, new, "updated", fields) if fields else None


def _message_change(thread: dict[str, Any], msg: dict[str, Any], kind: str) -> dict[str, Any]:
    fields = [
        {"label": "To", "before": None, "after": _people(msg.get("to"))},
        {"label": "Cc", "before": None, "after": _people(msg.get("cc"))},
        {"label": "Subject", "before": None, "after": thread.get("subject", "")},
        {"label": "Message", "before": None, "after": _clip(msg.get("body", ""))},
    ]
    if msg.get("attachments"):
        fields.append({"label": "Attached", "before": None, "after": _docs(msg["attachments"])})
    ch = _change("threads", thread, kind, [f for f in fields if f["after"]])
    ch["focus"] = [f'[data-thread-id="{thread["id"]}"]', f'[id="{msg.get("id", "")}"]']
    return ch


def _change(coll: str, obj: dict[str, Any], kind: str, fields: list[dict]) -> dict[str, Any]:
    oid = obj.get("id", "")
    what, url, focus = _where(coll, obj)
    if kind == "updated" and coll in ("deals", "calendar"):
        focus = [f'[data-field="{f["key"]}"]' for f in fields if f.get("key")] + focus
    for f in fields:
        f.pop("key", None)
    return {
        "app": APP[coll],
        "kind": kind,
        "type": coll,
        "id": oid,
        "what": what,
        "url": url,
        "focus": focus,
        "fields": fields,
    }


def _where(coll: str, o: dict[str, Any]) -> tuple[str, str, list[str]]:
    """What the object is called, the page that shows it, and what to point at there."""
    oid = o.get("id", "")
    if coll == "deals":
        return f"Deal: {o.get('name', oid)}", f"/crm/deal/{oid}", []
    if coll == "activities":
        kind = (o.get("type") or "note").capitalize()
        url = f"/crm/deal/{o['deal_id']}" if o.get("deal_id") else "/crm"
        return f"{kind} in Habspot", url, [f"#activity-{oid}"]
    if coll == "contacts":
        name = " ".join(x for x in (o.get("first_name"), o.get("last_name")) if x)
        return f"Contact: {name or oid}", f"/crm/contact/{oid}", []
    if coll == "companies":
        return f"Company: {o.get('name', oid)}", f"/crm/company/{oid}", []
    if coll == "threads":
        return (
            f"Email: {o.get('subject', '')}",
            f"/mail/thread/{oid}",
            [f'[data-thread-id="{oid}"]'],
        )
    if coll == "docs":
        return (
            f"Document: {o.get('name', oid)}",
            f"/drive/doc/{oid}",
            [f'[data-doc-id="{oid}"]', '[data-field="name"]'],
        )
    if coll == "calendar":
        return (
            f"Event: {o.get('title', oid)}",
            f"/calendar/event/{oid}",
            [f'[data-event-id="{oid}"]', '[data-field="title"]'],
        )
    return oid, "", []


# ---------- fields and values ----------


def _shown(coll: str, key: str) -> bool:
    """Fields worth showing; the rest are internal links or copies of other fields."""
    hidden = {
        "docs": {"body", "copied_from", "owner", "participants", "account", "deal"},
        "calendar": {"end", "account"},
        "activities": {"company_id", "contact_ids", "author", "deal_id"},
        "deals": {"company_id", "owner"},
    }
    return key not in hidden.get(coll, set())


def _field(coll: str, key: str, before: Any, after: Any) -> dict[str, Any]:
    label = LABELS.get(key) or key.replace("_", " ").capitalize()
    return {"key": key, "label": label, "before": _fmt(key, before), "after": _fmt(key, after)}


def _fmt(key: str, v: Any) -> str | None:
    if v is None or v == "" or v == []:
        return None
    if key == "stage":
        return STAGES.get(v, str(v))
    if key == "amount" and isinstance(v, (int, float)):
        return f"${v:,.0f}"
    if key == "discount_pct":
        return f"{_num(v)}%"
    if key == "attendees":
        return _people(v)
    if key == "shared_with":
        return ", ".join(s.get("email", "") for s in v if isinstance(s, dict))
    if key == "folder_id":
        f = store.get("folders", v) or {}
        return f.get("path") or f.get("name") or str(v)
    if key in ("start", "end", "due", "close_date", "next_step_date"):
        return _when(str(v))
    if key == "body":
        return _clip(str(v))
    if key in ("deal", "deal_id"):
        return (store.get("deals", v) or {}).get("name") or str(v)
    if key == "offer" and isinstance(v, dict):
        return _offer(v)
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if key == "type":
        return str(v).capitalize()
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    if isinstance(v, dict):
        return ", ".join(f"{k}: {x}" for k, x in v.items() if x not in (None, "", [], {}))
    return str(v)


def _when(v: str) -> str:
    try:
        if len(v) <= 10:
            return datetime.fromisoformat(v).strftime("%a %b %-d, %Y")
        return datetime.fromisoformat(v).strftime("%a %b %-d, %Y, %-I:%M %p")
    except ValueError:
        return v


def _people(v: Any) -> str:
    if not v:
        return ""
    if isinstance(v, str):
        return v
    out = []
    for p in v:
        if isinstance(p, dict):
            name, email = p.get("name"), p.get("email", "")
            out.append(f"{name} <{email}>" if name else email)
        else:
            out.append(str(p))
    return ", ".join(out)


def _offer(o: dict[str, Any]) -> str:
    parts = [str(o.get("plan") or "").capitalize()]
    if o.get("locations"):
        parts.append(f"{o['locations']} locations")
    parts.append(f"{_num(o.get('discount_pct') or 0)}% off")
    parts.append("onboarding included" if o.get("onboarding") else "no onboarding")
    if o.get("valid_until"):
        parts.append(f"valid until {_when(str(o['valid_until']))}")
    return ", ".join(p for p in parts if p)


def _num(v: Any) -> str:
    return f"{v:g}" if isinstance(v, float) else str(v)


def _docs(ids: list[str]) -> str:
    return ", ".join((store.get("docs", i) or {}).get("name", i) for i in ids)


def _clip(s: str) -> str:
    s = s.strip()
    return s if len(s) <= BODY_CHARS else s[: BODY_CHARS - 1].rstrip() + "…"
