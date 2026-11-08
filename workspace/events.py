"""Event log + the single commit path every write goes through.

read actions  -> log_read()   : logged, never gated
side events   -> emit()       : logged, never gated (e.g. jmail.attach, quote.discount)
write actions -> commit()     : derive ctx -> monitor.check() -> allow/flag/pause/block -> apply + log

See docs/EVENT-CONTRACT.md for the shape and how to adapt it.
"""

import copy
import json
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException

from . import catalog, changes, monitor, store

STAGES = ["new", "discovery", "demo", "proposal", "negotiation", "closed_won", "closed_lost"]
OPEN_STAGES = STAGES[:5]

# ---------------------------------------------------------------- run state

RUN: dict[str, Any] = {}
RUN_STATE: dict[str, Any] = {}
EVENTS: list[dict] = []  # events of the active run (history sent to the monitor)
PENDING: dict[
    str, dict
] = {}  # approval_id -> {"event": ..., "request": {method, path, query, body}}
UNDO: dict[str, dict] = {}  # event_id -> {"type": ..., "before": ...}
LEARNED: list[dict] = []  # rules learned from Allow/Block reasons; survive world resets (ADR 0008)
_counter = {"n": 0}
_last_read: dict[str, float] = {}

# Who is acting in this request (ADR 0005): "agent" requests (the scenario runner and the live
# agent, header X-Actor: agent) are logged and gated; "human" requests (someone browsing the apps)
# are never gated, and their reads aren't logged, so looking at the apps doesn't change the run.
ACTOR: ContextVar[str] = ContextVar("ACTOR", default="human")
# The request being handled: set by the state middleware (method/path/query) and web.body() (body).
# A paused write stores it, so approving later replays it. No closures, so it survives being saved
# to Redis and approved on another instance (ADR 0003).
CURRENT_REQUEST: ContextVar[dict | None] = ContextVar("CURRENT_REQUEST", default=None)
# Set while an approved request is replayed: the first matching commit skips the monitor.
APPROVED: ContextVar[dict | None] = ContextVar("APPROVED", default=None)
_REPLAY: dict[str, Callable[[dict], Awaitable[dict]]] = {}


def set_replayer(fn: Callable[[dict], Awaitable[dict]]) -> None:
    _REPLAY["fn"] = fn


def snapshot() -> dict:
    """Everything that must survive between requests, as plain JSON."""
    return {
        "data": store.DATA,
        "run": RUN,
        "run_state": RUN_STATE,
        "events": EVENTS,
        "pending": PENDING,
        "undo": UNDO,
        "learned": LEARNED,
        "counter": _counter["n"],
    }


def restore(snap: dict | None) -> None:
    """Load a snapshot in place (templates hold references to RUN, so never rebind it)."""
    if snap is None:
        store.reset()
        start_run()
        return
    store.load(snap["data"])
    for target, key in (
        (RUN, "run"),
        (RUN_STATE, "run_state"),
        (PENDING, "pending"),
        (UNDO, "undo"),
    ):
        target.clear()
        target.update(snap.get(key) or {})
    EVENTS[:] = snap.get("events") or []
    LEARNED[:] = snap.get("learned") or []
    _counter["n"] = max(_counter["n"], snap.get("counter", 0))


def start_run(
    agent: str = "human",
    account_id: str | None = None,
    actor: str = "human",
    label: str = "",
    run_id: str | None = None,
) -> dict:
    RUN.clear()
    RUN.update(
        {
            "id": run_id or time.strftime("run_%Y%m%d_%H%M%S_") + store.new_id("r")[2:],
            "agent": agent,
            "account_id": account_id,
            "actor": actor,
            "label": label,
            "started_at": _now(),
        }
    )
    RUN_STATE.clear()
    RUN_STATE.update({"last_email_source": "trusted_internal", "last_transcript_deal": None})
    EVENTS.clear()
    PENDING.clear()
    UNDO.clear()
    _last_read.clear()
    store.save()
    _log(_base("session", "session.start", None, None, {}, {}), decision="allow")
    return RUN


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _base(
    app: str, action: str, obj_type: str | None, obj_id: str | None, args: dict, ctx: dict
) -> dict:
    _counter["n"] += 1
    ev = {
        "id": f"ev_{int(time.time() * 1000)}_{_counter['n']}",
        "ts": _now(),
        "run_id": RUN.get("id"),
        "run": {
            "agent": RUN.get("agent"),
            "actor": RUN.get("actor"),
            "account_id": RUN.get("account_id"),
        },
        "app": app,
        "action": action,
        "object": {"type": obj_type, "id": obj_id} if obj_type else None,
        "args": args,
        "ctx": {k: v for k, v in ctx.items() if v is not None},
    }
    ev["catalog_action"] = catalog.to_catalog(ev)
    return ev


def _log(ev: dict, decision: str = "allow", score: float | None = None, reason: str = "") -> dict:
    ev["decision"] = decision
    ev["score"] = score
    ev["reason"] = reason
    ev.setdefault("by", ACTOR.get())
    EVENTS.append(ev)
    store.save()
    return ev


# ---------------------------------------------------------------- context derivation

RECIPIENT_RANK = [
    "internal",
    "known_contact",
    "new_contact",
    "new_external_domain",
    "do_not_contact",
    "competitor",
]


def recipient_class(email: str) -> str:
    d = store.domain_of(email)
    if d == store.SELLER_DOMAIN:
        return "internal"
    co = store.company_by_domain(d)
    if co and co.get("type") == "competitor":
        return "competitor"
    c = store.contact_by_email(email)
    if c:
        if c.get("status") in ("do_not_contact", "unsubscribed"):
            return "do_not_contact"
        return "known_contact"
    if co:
        return "new_contact"
    return "new_external_domain"


def recipients_class(emails: list[str]) -> str:
    """Worst recipient wins."""
    classes = [recipient_class(e) for e in emails if e] or ["internal"]
    return max(classes, key=RECIPIENT_RANK.index)


def stage_change(old: str, new: str, deal: dict) -> str:
    if old == new:
        return "stage_same"
    if old == "closed_won":
        return "reopen_won"
    if new == "closed_won":
        return "closed_won_signed" if deal.get("contract_signed") else "closed_won_unsigned"
    if new == "closed_lost":
        return "stage_closed_lost"
    if old in OPEN_STAGES and new in OPEN_STAGES:
        d = OPEN_STAGES.index(new) - OPEN_STAGES.index(old)
        return "stage_forward" if d == 1 else ("stage_skip" if d > 1 else "stage_backward")
    return "stage_backward"  # e.g. closed_lost -> open


def amount_change(old: float, new: float) -> str:
    if not old:
        return "amount_changed_large"
    pct = abs(new - old) / old * 100
    return (
        "amount_changed_large"
        if pct > store.POLICY["large_amount_change_pct"]
        else "amount_changed_small"
    )


def close_date_change(old: str, new: str) -> str:
    try:
        d = abs((date.fromisoformat(new[:10]) - date.fromisoformat(old[:10])).days)
    except (TypeError, ValueError):
        return "close_date_changed_large"
    return (
        "close_date_changed_large"
        if d > store.POLICY["large_close_date_change_days"]
        else "close_date_changed_small"
    )


def discount_class(pct: float) -> str:
    return "within_limit" if pct <= store.POLICY["max_discount_rep"] else "over_limit"


def account_of(obj_type: str | None, obj: dict | None) -> str | None:
    """Company id an object belongs to (for agent D's scope tag)."""
    if not obj:
        return None
    if obj_type == "company":
        return obj["id"]
    if obj_type in ("contact", "deal"):
        return obj.get("company_id")
    if obj_type in ("activity", "note", "task"):
        return obj.get("company_id")
    if obj_type in ("doc", "event"):
        acc = obj.get("account")
        return f"co_{acc}" if acc else None
    if obj_type == "thread":
        for m in obj.get("messages", []):
            for e in [m["from"]["email"]] + [t["email"] for t in m.get("to", [])]:
                co = store.company_by_domain(store.domain_of(e))
                if co:
                    return co["id"]
    return None


def scope_tag(obj_type: str | None, obj: dict | None) -> str | None:
    acc = RUN.get("account_id")
    if not acc:
        return None
    owner = account_of(obj_type, obj)
    if owner is None:
        return None
    return "in_scope" if owner == acc else "out_of_scope"


def target_tag(deal_id: str | None) -> str | None:
    src = RUN_STATE.get("last_transcript_deal")
    if not src or not deal_id:
        return None
    return "matches_source" if src == deal_id else "other_deal"


# ---------------------------------------------------------------- public API


def log_read(
    app: str,
    action: str,
    obj_type: str,
    obj_id: str,
    ctx: dict | None = None,
    args: dict | None = None,
) -> dict | None:
    """Log a read. Collapses repeats of the same object within 5 seconds (reloads, screenshot retries)."""
    if not RUN:
        start_run()
    if ACTOR.get() != "agent":
        return None
    key = f"{action}:{obj_id}:{json.dumps(args or {}, sort_keys=True)}"
    t = time.time()
    if t - _last_read.get(key, 0) < 5:
        return None
    _last_read[key] = t
    obj = (
        store.get(store.TYPE_TO_COLL.get(obj_type, ""), obj_id)
        if obj_type in store.TYPE_TO_COLL
        else None
    )
    ctx = dict(ctx or {})
    ctx.setdefault("scope", scope_tag(obj_type, obj))
    # run memory used by later context tags
    if action == "jmail.open_thread" and ctx.get("source"):
        RUN_STATE["last_email_source"] = ctx["source"]
    if action == "jdrive.open" and obj and obj.get("kind") == "transcript" and obj.get("deal"):
        RUN_STATE["last_transcript_deal"] = obj["deal"]
    ev = _base(app, action, obj_type, obj_id, args or {}, ctx)
    verdict = monitor.check(ev, EVENTS, RUN, RUN_STATE, gate=False)
    _attach(ev, verdict)
    return _log(
        ev, verdict.get("decision", "allow"), verdict.get("score"), verdict.get("reason", "")
    )


def _attach(ev: dict, verdict: dict) -> None:
    extra = {k: v for k, v in verdict.items() if k not in ("decision", "score", "reason")}
    if extra:
        ev["monitor"] = extra  # checks, failed, headline... shown by the canvas and /events


def emit(
    app: str,
    action: str,
    obj_type: str | None,
    obj_id: str | None,
    ctx: dict,
    args: dict | None = None,
) -> dict:
    """Ungated side event that adds risk signal (e.g. jmail.attach:confidential, quote.discount:over_limit)."""
    if not RUN:
        start_run()
    if ACTOR.get() != "agent":
        return None
    return _log(_base(app, action, obj_type, obj_id, args or {}, ctx))


def commit(
    app: str,
    action: str,
    obj_type: str | None,
    obj_id: str | None,
    args: dict,
    ctx: dict,
    apply: Callable[[], Any],
    irreversible: bool = False,
) -> dict:
    """The ONE path for every write. Returns {"decision", "event", "result"}; raises 403 on block."""
    if not RUN:
        start_run()
    ctx = dict(ctx)
    if irreversible:
        ctx.setdefault("source", RUN_STATE.get("last_email_source"))
    obj = store.snapshot(obj_type, obj_id) if obj_type else None
    ctx.setdefault("scope", scope_tag(obj_type, obj))
    if obj_type == "deal":
        ctx.setdefault("target", target_tag(obj_id))
    ev = _base(app, action, obj_type, obj_id, args, ctx)
    ev["irreversible"] = irreversible
    if obj is not None:
        ev["before"] = obj

    approved = APPROVED.get()
    if ACTOR.get() != "agent":
        verdict = {"decision": "allow", "reason": "done by a person in the app"}
    elif (
        approved
        and not approved.get("used")
        and approved.get("catalog_action") == ev["catalog_action"]
    ):
        approved["used"] = True
        verdict = {
            "decision": "allow",
            "reason": "Approved by a person"
            + (f": {approved['reason']}" if approved.get("reason") else ""),
        }
        ev["approval_id"] = approved["approval_id"]
    else:
        verdict = monitor.check(ev, EVENTS, RUN, RUN_STATE, gate=True)
    decision, score, reason = verdict["decision"], verdict.get("score"), verdict.get("reason", "")
    _attach(ev, verdict)

    if decision == "block":
        _log(ev, "block", score, reason)
        raise HTTPException(
            status_code=403,
            detail={
                "decision": "block",
                "reason": reason or "Blocked by Sentinel",
                "event_id": ev["id"],
            },
        )

    if decision == "pause":
        approval_id = f"ap_{ev['id']}"
        PENDING[approval_id] = {"event": ev, "request": CURRENT_REQUEST.get()}
        _log(ev, "pause", score, reason)
        raise HTTPException(
            status_code=202,
            detail={
                "decision": "pause",
                "reason": reason or "Waiting for approval",
                "approval_id": approval_id,
                "event_id": ev["id"],
            },
        )

    result = apply()
    store.save()
    if obj is not None:
        UNDO[ev["id"]] = {"type": obj_type, "before": obj}
    _log(ev, decision, score, reason)
    return {"decision": decision, "event": ev, "result": result, "reason": reason}


def learn(decision: str, ev: dict, reason: str, by: str) -> dict | None:
    """A person's reason for allowing/blocking a paused step becomes a rule (PDF: 'each reason
    becomes a new rule'). The monitor applies it to later steps with the same catalog action."""
    if not reason:
        return None
    mon = ev.get("monitor") or {}
    failed = mon.get("failed") or []
    rule = {
        "id": f"lr_{len(LEARNED) + 1:03d}",
        "entity": mon.get("entity"),
        "decision": decision,
        "catalog_action": ev.get("catalog_action"),
        "ctx": ev.get("ctx", {}),
        "checks": failed,
        "agent": (ev.get("run") or {}).get("agent"),
        "reason": reason,
        "by": by,
        "learned_at": _now(),
        "from_event": ev.get("id"),
    }
    LEARNED.append(rule)
    store.save()
    return rule


async def approve(approval_id: str, approver: str = "u_dana", reason: str = "") -> dict:
    """Allow a paused write: replay its original request with the gate told it's approved."""
    p = PENDING.pop(approval_id, None)
    if not p:
        raise HTTPException(404, "No such pending approval")
    ev = p["event"]
    if not p.get("request") or "fn" not in _REPLAY:
        raise HTTPException(409, "This paused step can't be replayed (no recorded request)")
    token = APPROVED.set(
        {"approval_id": approval_id, "catalog_action": ev["catalog_action"], "reason": reason}
    )
    snap = changes.capture()
    try:
        result = await _REPLAY["fn"](p["request"])
    finally:
        APPROVED.reset(token)
    diff = changes.diff(snap, store.DATA)
    rule = learn("allow", ev, reason, approver)
    _log(
        _base(
            "sentinel",
            "sentinel.approved",
            None,
            None,
            {
                "approval_id": approval_id,
                "event_id": ev["id"],
                "by": approver,
                "reason": reason,
                "rule_id": rule and rule["id"],
                "changes": diff,
            },
            {},
        )
    )
    return {"ok": True, "result": result, "rule": rule, "changes": diff}


async def reject(approval_id: str, approver: str = "u_dana", reason: str = "") -> dict:
    p = PENDING.pop(approval_id, None)
    if not p:
        raise HTTPException(404, "No such pending approval")
    rule = learn("block", p["event"], reason, approver)
    _log(
        _base(
            "sentinel",
            "sentinel.rejected",
            None,
            None,
            {
                "approval_id": approval_id,
                "event_id": p["event"]["id"],
                "by": approver,
                "reason": reason,
                "rule_id": rule and rule["id"],
            },
            {},
        )
    )
    return {"ok": True, "rule": rule}


def sources() -> list[dict]:
    """Text of everything the agent has read in this run (for the monitor's fact check)."""
    out, seen = [], set()
    for e in EVENTS:
        o = e.get("object") or {}
        key = (o.get("type"), o.get("id"))
        if e.get("app") == "ui" or not o.get("id") or key in seen:
            continue
        if not (
            e["action"].startswith(("jmail.open", "jdrive.open", "habspot.open", "calendar.open"))
        ):
            continue
        seen.add(key)
        obj = (
            store.get(store.TYPE_TO_COLL.get(o["type"], ""), o["id"])
            if o["type"] in store.TYPE_TO_COLL
            else None
        )
        if not obj:
            continue
        if o["type"] == "doc":
            text = obj.get("body", "")
        elif o["type"] == "thread":
            text = "\n\n".join(
                f"From: {m['from']['email']}\nDate: {m['ts']}\n{m.get('body', '')}"
                for m in obj.get("messages", [])
            )
        elif o["type"] == "deal":
            notes = [a for a in store.items("activities") if a.get("deal_id") == obj["id"]]
            text = (
                json.dumps(
                    {
                        k: obj.get(k)
                        for k in (
                            "name",
                            "stage",
                            "amount",
                            "locations",
                            "plan",
                            "close_date",
                            "next_step",
                            "discount_pct",
                            "contract_signed",
                        )
                    }
                )
                + "\n"
                + "\n".join(
                    f"[{a.get('type')} {a.get('ts', '')[:10]}] {a.get('title', '')}: {a.get('body', '')}"
                    for a in notes
                )
            )
        else:
            text = json.dumps(obj)
        out.append(
            {
                "type": o["type"],
                "id": o["id"],
                "read_at": e["ts"],
                "trusted": e.get("ctx", {}).get("source") != "untrusted_external",
                "text": text,
            }
        )
    return out


def undo(event_id: str) -> dict:
    u = UNDO.pop(event_id, None)
    if not u:
        raise HTTPException(404, "Nothing to undo for this event")
    store.replace(store.TYPE_TO_COLL[u["type"]], copy.deepcopy(u["before"]))
    store.save()
    _log(
        _base(
            "sentinel", "sentinel.undone", u["type"], u["before"]["id"], {"event_id": event_id}, {}
        )
    )
    return {"ok": True}
