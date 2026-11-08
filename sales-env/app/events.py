"""Event log + the single commit path every write goes through.

read actions  -> log_read()   : logged, never gated
side events   -> emit()       : logged, never gated (e.g. jmail.attach, quote.discount)
write actions -> commit()     : derive ctx -> monitor.check() -> allow/flag/pause/block -> apply + log

See docs/EVENT-CONTRACT.md for the shape and how to adapt it.
"""
import copy
import json
import time
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException

from . import catalog, monitor, store

RUNS_DIR = store.ROOT / "runs"

STAGES = ["new", "discovery", "demo", "proposal", "negotiation", "closed_won", "closed_lost"]
OPEN_STAGES = STAGES[:5]

# ---------------------------------------------------------------- run state

RUN: Dict[str, Any] = {}
RUN_STATE: Dict[str, Any] = {}
EVENTS: List[dict] = []          # events of the active run (history sent to the monitor)
PENDING: Dict[str, dict] = {}    # approval_id -> {"event": ..., "apply": fn}
UNDO: Dict[str, dict] = {}       # event_id -> {"type": ..., "before": ...}
_counter = {"n": 0}
_last_read: Dict[str, float] = {}


def start_run(agent: str = "human", account_id: Optional[str] = None, actor: str = "human",
              label: str = "", run_id: Optional[str] = None) -> dict:
    RUN.clear()
    RUN.update({
        "id": run_id or time.strftime("run_%Y%m%d_%H%M%S_") + store.new_id("r")[2:],
        "agent": agent, "account_id": account_id, "actor": actor, "label": label,
        "started_at": _now(),
    })
    RUN_STATE.clear()
    RUN_STATE.update({"last_email_source": "trusted_internal", "last_transcript_deal": None})
    EVENTS.clear()
    PENDING.clear()
    UNDO.clear()
    _last_read.clear()
    _log(_base("session", "session.start", None, None, {}, {}), decision="allow")
    return RUN


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _base(app: str, action: str, obj_type: Optional[str], obj_id: Optional[str],
          args: dict, ctx: dict) -> dict:
    _counter["n"] += 1
    ev = {
        "id": f"ev_{int(time.time()*1000)}_{_counter['n']}",
        "ts": _now(),
        "run_id": RUN.get("id"),
        "run": {"agent": RUN.get("agent"), "actor": RUN.get("actor"), "account_id": RUN.get("account_id")},
        "app": app,
        "action": action,
        "object": {"type": obj_type, "id": obj_id} if obj_type else None,
        "args": args,
        "ctx": {k: v for k, v in ctx.items() if v is not None},
    }
    ev["catalog_action"] = catalog.to_catalog(ev)
    return ev


def _log(ev: dict, decision: str = "allow", score: Optional[float] = None, reason: str = "") -> dict:
    ev["decision"] = decision
    ev["score"] = score
    ev["reason"] = reason
    EVENTS.append(ev)
    RUNS_DIR.mkdir(exist_ok=True)
    with open(RUNS_DIR / f"{ev['run_id']}.jsonl", "a") as f:
        f.write(json.dumps(ev) + "\n")
    return ev


# ---------------------------------------------------------------- context derivation

RECIPIENT_RANK = ["internal", "known_contact", "new_contact", "new_external_domain", "do_not_contact", "competitor"]


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


def recipients_class(emails: List[str]) -> str:
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
    return "amount_changed_large" if pct > store.POLICY["large_amount_change_pct"] else "amount_changed_small"


def close_date_change(old: str, new: str) -> str:
    try:
        d = abs((date.fromisoformat(new[:10]) - date.fromisoformat(old[:10])).days)
    except Exception:
        return "close_date_changed_large"
    return "close_date_changed_large" if d > store.POLICY["large_close_date_change_days"] else "close_date_changed_small"


def discount_class(pct: float) -> str:
    return "within_limit" if pct <= store.POLICY["max_discount_rep"] else "over_limit"


def account_of(obj_type: Optional[str], obj: Optional[dict]) -> Optional[str]:
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


def scope_tag(obj_type: Optional[str], obj: Optional[dict]) -> Optional[str]:
    acc = RUN.get("account_id")
    if not acc:
        return None
    owner = account_of(obj_type, obj)
    if owner is None:
        return None
    return "in_scope" if owner == acc else "out_of_scope"


def target_tag(deal_id: Optional[str]) -> Optional[str]:
    src = RUN_STATE.get("last_transcript_deal")
    if not src or not deal_id:
        return None
    return "matches_source" if src == deal_id else "other_deal"


# ---------------------------------------------------------------- public API

def log_read(app: str, action: str, obj_type: str, obj_id: str, ctx: Optional[dict] = None,
             args: Optional[dict] = None) -> Optional[dict]:
    """Log a read. Collapses repeats of the same object within 5 seconds (reloads, screenshot retries)."""
    if not RUN:
        start_run()
    key = f"{action}:{obj_id}:{json.dumps(args or {}, sort_keys=True)}"
    t = time.time()
    if t - _last_read.get(key, 0) < 5:
        return None
    _last_read[key] = t
    obj = store.get(store.TYPE_TO_COLL.get(obj_type, ""), obj_id) if obj_type in store.TYPE_TO_COLL else None
    ctx = dict(ctx or {})
    ctx.setdefault("scope", scope_tag(obj_type, obj))
    # run memory used by later context tags
    if action == "jmail.open_thread" and ctx.get("source"):
        RUN_STATE["last_email_source"] = ctx["source"]
    if action == "jdrive.open" and obj and obj.get("kind") == "transcript" and obj.get("deal"):
        RUN_STATE["last_transcript_deal"] = obj["deal"]
    return _log(_base(app, action, obj_type, obj_id, args or {}, ctx))


def emit(app: str, action: str, obj_type: Optional[str], obj_id: Optional[str], ctx: dict,
         args: Optional[dict] = None) -> dict:
    """Ungated side event that adds risk signal (e.g. jmail.attach:confidential, quote.discount:over_limit)."""
    if not RUN:
        start_run()
    return _log(_base(app, action, obj_type, obj_id, args or {}, ctx))


def commit(app: str, action: str, obj_type: Optional[str], obj_id: Optional[str], args: dict,
           ctx: dict, apply: Callable[[], Any], irreversible: bool = False) -> dict:
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

    verdict = monitor.check(ev, EVENTS, RUN)
    decision, score, reason = verdict["decision"], verdict.get("score"), verdict.get("reason", "")

    if decision == "block":
        _log(ev, "block", score, reason)
        raise HTTPException(status_code=403, detail={"decision": "block", "reason": reason or "Blocked by Sentinel", "event_id": ev["id"]})

    if decision == "pause":
        approval_id = f"ap_{ev['id']}"
        PENDING[approval_id] = {"event": ev, "apply": apply}
        _log(ev, "pause", score, reason)
        raise HTTPException(status_code=202, detail={"decision": "pause", "reason": reason or "Waiting for approval",
                                                     "approval_id": approval_id, "event_id": ev["id"]})

    result = apply()
    store.save()
    if obj is not None:
        UNDO[ev["id"]] = {"type": obj_type, "before": obj}
    _log(ev, decision, score, reason)
    return {"decision": decision, "event": ev, "result": result, "reason": reason}


def approve(approval_id: str, approver: str = "u_dana") -> dict:
    p = PENDING.pop(approval_id, None)
    if not p:
        raise HTTPException(404, "No such pending approval")
    result = p["apply"]()
    store.save()
    ev = p["event"]
    _log(_base("sentinel", "sentinel.approved", None, None, {"approval_id": approval_id, "event_id": ev["id"], "by": approver}, {}))
    return {"ok": True, "result": result}


def reject(approval_id: str, approver: str = "u_dana") -> dict:
    p = PENDING.pop(approval_id, None)
    if not p:
        raise HTTPException(404, "No such pending approval")
    _log(_base("sentinel", "sentinel.rejected", None, None, {"approval_id": approval_id, "event_id": p["event"]["id"], "by": approver}, {}))
    return {"ok": True}


def undo(event_id: str) -> dict:
    u = UNDO.pop(event_id, None)
    if not u:
        raise HTTPException(404, "Nothing to undo for this event")
    store.replace(store.TYPE_TO_COLL[u["type"]], copy.deepcopy(u["before"]))
    store.save()
    _log(_base("sentinel", "sentinel.undone", u["type"], u["before"]["id"], {"event_id": event_id}, {}))
    return {"ok": True}
