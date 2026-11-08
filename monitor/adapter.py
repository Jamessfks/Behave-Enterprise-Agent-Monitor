"""Workspace events -> what the three checks read (ADR 0006). Pure: never imports `workspace`.

The workspace logs one event per read and write (docs/event-contract.md sections 3-4). This
module turns them into:
- step events for the step model (`steps`): only steps that happened, by the agent, in order;
  type "search" for *.search, else "view" with action_id = catalog_action;
- the text of every object the agent opened (`sources`), for the fact check;
- the rule view of one candidate step (`rule_view`), for the rules check: action, ctx, typed
  values, the company, deal and offer it touches, the run, and facts from the deal's call.

Everything is computed from the events plus the workspace data passed in (`store.DATA`).
"""

from __future__ import annotations

import json
from typing import Any

from monitor import facts as facts_mod
from monitor.context import company_context, price
from monitor.rules import holds

TYPE_TO_COLL = {
    "user": "users",
    "company": "companies",
    "contact": "contacts",
    "deal": "deals",
    "activity": "activities",
    "note": "activities",
    "task": "activities",
    "thread": "threads",
    "folder": "folders",
    "doc": "docs",
    "event": "calendar",
}
DEAL_FIELDS = (
    "name",
    "stage",
    "amount",
    "locations",
    "plan",
    "close_date",
    "next_step",
    "next_step_date",
    "discount_pct",
    "contract_signed",
)
COMPANY_FIELDS = ("name", "domain", "industry", "hq", "locations", "hourly_staff", "description")
OFFER_KEYS = ("plan", "locations", "discount_pct", "onboarding")


def _cfg() -> dict[str, Any]:
    return company_context()["actions"]


# ---------------------------------------------------------------- data lookups


def get(data: dict[str, Any] | None, obj_type: str | None, obj_id: str | None) -> dict | None:
    coll = TYPE_TO_COLL.get(obj_type or "")
    if not coll or not obj_id or not data:
        return None
    return next((o for o in data.get(coll) or [] if o.get("id") == obj_id), None)


def domain_of(email: str) -> str:
    return email.split("@")[-1].lower().strip() if "@" in (email or "") else ""


def company_by_domain(data: dict[str, Any] | None, domain: str) -> dict | None:
    if not domain:
        return None
    return next(
        (
            c
            for c in (data or {}).get("companies") or []
            if (c.get("domain") or "").lower() == domain
        ),
        None,
    )


def _emails(v: Any) -> list[str]:
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if "@" in x]
    out = []
    for x in v or []:
        e = x.get("email") if isinstance(x, dict) else x
        if isinstance(e, str) and "@" in e:
            out.append(e.strip())
    return out


def account_of(obj_type: str | None, obj: dict | None, data: dict[str, Any] | None) -> str | None:
    """Company id an object belongs to (same logic as the workspace's events.account_of)."""
    if not obj:
        return None
    if obj_type == "company":
        return obj.get("id")
    if obj_type in ("contact", "deal", "activity", "note", "task"):
        return obj.get("company_id")
    if obj_type in ("doc", "event"):
        acc = obj.get("account") or (obj.get("offer") or {}).get("account")
        return f"co_{acc}" if acc else None
    if obj_type == "thread":
        for m in obj.get("messages") or []:
            for e in [m.get("from", {}).get("email", "")] + _emails(m.get("to")):
                co = company_by_domain(data, domain_of(e))
                if co:
                    return co["id"]
    return None


def _obj(ev: dict[str, Any], data: dict[str, Any] | None) -> tuple[str | None, dict | None]:
    o = ev.get("object") or {}
    return o.get("type"), ev.get("before") or get(data, o.get("type"), o.get("id"))


def entity_of(ev: dict[str, Any], data: dict[str, Any] | None) -> str | None:
    """The company the step touches: its object's account, else the deal or recipients in args."""
    t, obj = _obj(ev, data)
    ent = account_of(t, obj, data)
    if ent:
        return ent
    args = ev.get("args") or {}
    deal = get(data, "deal", args.get("deal_id") or args.get("deal"))
    if deal:
        return deal.get("company_id")
    for key in ("to", "cc", "attendees", "email"):
        for e in _emails(args.get(key)):
            co = company_by_domain(data, domain_of(e))
            if co and co.get("domain") != company_context()["company"]["seller_domain"]:
                return co["id"]
    return None


# ---------------------------------------------------------------- steps


def is_write(ev: dict[str, Any]) -> bool:
    """Writes go through the workspace's commit(), which always sets `irreversible`."""
    return "irreversible" in ev


def is_step(ev: dict[str, Any]) -> bool:
    """A meaning-level step by the agent (not a click, session marker, side signal or a person)."""
    cfg = _cfg()
    return (
        ev.get("app") not in cfg["skip_apps"]
        and ev.get("action") not in cfg["side_actions"]
        and ev.get("by") != "human"
    )


def applied(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agent steps that happened. A paused or blocked write didn't; if a person approves it, the
    workspace replays it as a new event (with `approval_id`, decision allow), which counts."""
    return [e for e in history if is_step(e) and e.get("decision") not in ("pause", "block")]


def _num(v: Any) -> float | int | None:
    try:
        f = float(str(v).replace(",", "").replace("$", "").rstrip("%"))
    except (TypeError, ValueError):
        return None
    return int(f) if f == int(f) else f


def _offer_values(o: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if o.get("plan"):
        out["plan"] = str(o["plan"]).lower()
    for k in ("locations", "discount_pct"):
        if o.get(k) not in (None, ""):
            out[k] = _num(o[k])
    return out


def values_of(ev: dict[str, Any]) -> dict[str, Any]:
    """The typed values a step writes, keyed by the fact-check's field names."""
    a = ev.get("action") or ""
    args = ev.get("args") or {}
    before = ev.get("before") or {}
    if a == "habspot.amount" and args.get("amount") not in (None, ""):
        return {"amount": _num(args["amount"])}
    if a == "habspot.close_date" and args.get("close_date"):
        return {"close_date": str(args["close_date"])[:10]}
    if a == "habspot.next_step" and args.get("next_step_date"):
        # The rep's plan, not a customer fact (bible 6.8: only amount and close date must come
        # from what the customer said), so it's shown but not fact-checked.
        return {"next_step_date": str(args["next_step_date"])[:10]}
    if a in ("habspot.quote_create", "quote.save"):
        return _offer_values(args)
    if a == "quote.send":
        return _offer_values(before.get("offer") or {})
    if a in ("habspot.contact_create", "habspot.contact_update"):
        out = {}
        name = " ".join(x for x in (args.get("first_name"), args.get("last_name")) if x)
        if name and a == "habspot.contact_create":
            out["contact_name"] = name
        if args.get("email"):
            out["contact_email"] = args["email"]
        if args.get("title"):
            out["contact_title"] = args["title"]
        return out
    if a == "calendar.create" and args.get("start"):
        return {"date": str(args["start"])[:10]}
    if a == "calendar.update" and (ev.get("ctx") or {}).get("change") == "time_moved":
        return {"date": str(args.get("start") or "")[:10]}
    return {}


def _ts(ev: dict[str, Any]) -> str:
    ts = str(ev.get("ts") or "1970-01-01T00:00:00+00:00")
    return ts.replace("+00:00", "Z") if ts.endswith("+00:00") else ts


def to_step(ev: dict[str, Any], data: dict[str, Any] | None, step: int) -> dict[str, Any]:
    action = ev.get("action") or ""
    args = ev.get("args") or {}
    search = action.endswith(".search")
    obj = ev.get("object") or {}
    write = is_write(ev)
    return {
        "run_id": ev.get("run_id"),
        "step": step,
        "timestamp": _ts(ev),
        "type": "search" if search else "view",
        "action_id": None if search else (ev.get("catalog_action") or action),
        "query": (args.get("q") or args.get("label") or action) if search else None,
        "details": {
            "app": ev.get("app"),
            "action": action,
            "entity": entity_of(ev, data),
            "irreversible": bool(ev.get("irreversible")),
            "write": write,
            "draft": action in _cfg()["drafts"],
            "source": None if write else obj.get("id"),
            "values": values_of(ev),
        },
    }


def steps(history: list[dict[str, Any]], data: dict[str, Any] | None = None) -> list[dict]:
    return [to_step(e, data, i) for i, e in enumerate(applied(history))]


# ---------------------------------------------------------------- sources (fact check)


def _created_ids(events: list[dict[str, Any]]) -> set[str]:
    """Objects the run itself created: its own words never count as a source."""
    out = set()
    for e in events:
        if not is_write(e):
            continue
        args = e.get("args") or {}
        out |= {args[k] for k in ("doc_id", "new_doc_id", "note_id", "task_id") if args.get(k)}
        if e.get("action") in ("jdrive.create", "calendar.create", "habspot.contact_create"):
            out.add((e.get("object") or {}).get("id"))
    return {x for x in out if x}


def _own_sends(events: list[dict[str, Any]]) -> list[tuple[frozenset, int | None]]:
    out = []
    for e in events:
        if is_write(e) and e.get("action") in (
            "jmail.send",
            "jmail.reply",
            "jmail.forward",
            "quote.send",
            "quote.request_approval",
        ):
            args = e.get("args") or {}
            to = frozenset(x.lower() for x in _emails(args.get("to")) + _emails(args.get("cc")))
            out.append((to, args.get("body_chars")))
    return out


def _earliest_befores(events: list[dict[str, Any]]) -> dict[tuple, dict]:
    """The state of each object before the run first wrote it, so the agent's own value can't
    confirm itself."""
    out: dict[tuple, dict] = {}
    for e in events:
        o = e.get("object") or {}
        if is_write(e) and e.get("before") and o.get("id"):
            out.setdefault((o.get("type"), o["id"]), e["before"])
    return out


def _text(
    t: str, obj: dict, data: dict | None, created: set[str], own: list[tuple[frozenset, Any]]
) -> str:
    rep = company_context()["company"]["rep_email"]
    if t == "doc":
        return obj.get("body") or ""
    if t == "thread":
        parts = []
        for m in obj.get("messages") or []:
            sender = (m.get("from") or {}).get("email", "")
            to = frozenset(x.lower() for x in _emails(m.get("to")) + _emails(m.get("cc")))
            n = len(m.get("body") or "")
            if sender.lower() == rep and any(to == s and bc in (None, n) for s, bc in own):
                continue  # the agent's own message
            parts.append(f"From: {sender}\nDate: {m.get('ts', '')}\n{m.get('body', '')}")
        return "\n\n".join(parts)
    if t == "deal":
        notes = [
            a
            for a in (data or {}).get("activities") or []
            if a.get("deal_id") == obj.get("id") and a.get("id") not in created
        ]
        head = json.dumps({k: obj.get(k) for k in DEAL_FIELDS})
        return (
            head
            + "\n"
            + "\n".join(
                f"[{a.get('type')} {str(a.get('ts', ''))[:10]}] {a.get('title', '')}: {a.get('body', '')}"
                for a in notes
            )
        )
    if t == "company":
        return json.dumps({k: obj.get(k) for k in COMPANY_FIELDS})
    return json.dumps(obj)


def _title(t: str, obj: dict) -> str:
    if t == "thread":
        return obj.get("subject") or obj.get("id", "")
    if t == "contact":
        return " ".join(x for x in (obj.get("first_name"), obj.get("last_name")) if x)
    return obj.get("name") or obj.get("title") or obj.get("id", "")


def is_open(action: str) -> bool:
    return action.startswith(tuple(_cfg()["open_prefixes"])) and action != "jdrive.open_folder"


def sources(
    history: list[dict[str, Any]], data: dict[str, Any] | None, candidate: dict | None = None
) -> list[dict[str, Any]]:
    """Text of every object the agent opened earlier in the run, oldest read first.

    `index` is the read's position among the run's applied steps (for "was the conflict raised
    after reading it?"). For objects this run already wrote, the text is the earliest `before`
    snapshot; objects the run created and the agent's own messages are left out.
    """
    writes = [e for e in history if is_step(e)] + ([candidate] if candidate else [])
    befores = _earliest_befores(writes)
    created = _created_ids(writes)
    own = _own_sends(writes)
    out, seen = [], set()
    for i, e in enumerate(applied(history)):
        o = e.get("object") or {}
        key = (o.get("type"), o.get("id"))
        if is_write(e) or not o.get("id") or key in seen or not is_open(e.get("action", "")):
            continue
        seen.add(key)
        if o["id"] in created:
            continue
        obj = befores.get(key) or get(data, o["type"], o["id"])
        if not obj:
            continue
        out.append(
            {
                "id": o["id"],
                "type": o["type"],
                "title": _title(o["type"], obj),
                "entity": account_of(o["type"], obj, data),
                "kind": obj.get("kind"),
                "deal": obj.get("deal"),
                "index": i,
                "text": _text(o["type"], obj, data, created, own),
            }
        )
    return out


# ---------------------------------------------------------------- rule view


def deal_of(ev: dict[str, Any], data: dict[str, Any] | None, entity: str | None) -> dict | None:
    t, obj = _obj(ev, data)
    args = ev.get("args") or {}
    if t == "deal" and obj:
        return obj
    did = (obj or {}).get("deal") or (obj or {}).get("deal_id") or args.get("deal_id")
    did = did or args.get("deal")
    if did:
        return get(data, "deal", did)
    open_deals = [
        d
        for d in (data or {}).get("deals") or []
        if d.get("company_id") == entity and entity and not str(d.get("stage")).startswith("closed")
    ]
    return open_deals[0] if len(open_deals) == 1 else None


def _offer_doc_offers(data: dict | None, ids: list[str]) -> list[dict]:
    out = []
    for i in ids:
        d = get(data, "doc", i)
        if d and d.get("kind") == "offer" and d.get("offer"):
            out.append({**d["offer"], "doc_id": i})
    return out


def offer_of(ev: dict[str, Any], data: dict[str, Any] | None) -> dict | None:
    """The offer a step creates, saves, sends or attaches (the worst discount if several)."""
    a = ev.get("action") or ""
    args = ev.get("args") or {}
    before = ev.get("before") or {}
    if a == "habspot.quote_create":
        return {**{k: args.get(k) for k in OFFER_KEYS}, **_offer_values(args), "status": "draft"}
    if a == "quote.save":
        o = dict(before.get("offer") or {})
        o.update(_offer_values(args))
        if args.get("account"):
            o["account"] = args["account"]
        return {**o, "doc_id": (ev.get("object") or {}).get("id")}
    if a.startswith("quote.") and before.get("offer"):
        return {**before["offer"], "doc_id": before.get("id")}
    atts = args.get("attachments") or []
    offers = _offer_doc_offers(data, atts if isinstance(atts, list) else [atts])
    if offers:
        return max(offers, key=lambda o: _num(o.get("discount_pct")) or 0)
    return None


def run_offers(
    history: list[dict[str, Any]], data: dict[str, Any] | None, deal: dict | None
) -> list[dict]:
    """The deal's offers: in the workspace data, plus those created or saved in this run."""
    if not deal:
        return []
    slug = (deal.get("company_id") or "")[3:]
    by_id: dict[str, dict] = {}
    for d in (data or {}).get("docs") or []:
        o = d.get("offer")
        mine = d.get("deal") == deal["id"] or (
            o and o.get("account") == slug and d.get("deal") in (None, deal["id"])
        )
        if d.get("kind") == "offer" and o and mine:
            by_id[d["id"]] = {**o, "doc_id": d["id"]}
    for e in applied(history):
        a = e.get("action")
        if a == "habspot.quote_create" and (e.get("object") or {}).get("id") == deal["id"]:
            did = (e.get("args") or {}).get("doc_id") or f"_new{len(by_id)}"
            by_id.setdefault(did, offer_of(e, data) or {})
        elif a == "quote.save":
            o = offer_of(e, data) or {}
            if o.get("account") == slug or (e.get("before") or {}).get("deal") == deal["id"]:
                by_id[o.get("doc_id") or f"_save{len(by_id)}"] = o
        elif a == "quote.approved":
            did = (e.get("object") or {}).get("id")
            if did in by_id:
                by_id[did]["status"] = "approved"
    return list(by_id.values())


def segments(company: dict | None) -> list[str]:
    ind = ((company or {}).get("industry") or "").lower()
    return [s for s, words in company_context()["segments"].items() if any(w in ind for w in words)]


def transcript_of(data: dict[str, Any] | None, deal_id: str | None) -> dict | None:
    """The deal's call transcript (the latest call, if several): the primary source."""
    kind = company_context()["facts"]["primary_kind"]
    docs = [
        d
        for d in (data or {}).get("docs") or []
        if d.get("kind") == kind and d.get("deal") == deal_id and deal_id
    ]
    return max(docs, key=lambda d: str(d.get("call_date") or "")) if docs else None


def rule_view(
    event: dict[str, Any],
    history: list[dict[str, Any]],
    data: dict[str, Any] | None,
    run: dict[str, Any] | None,
    *,
    gate: bool,
) -> dict[str, Any]:
    """Everything a rule spec can test about one candidate step (dotted paths, monitor/rules.py)."""
    cc = company_context()
    entity = entity_of(event, data)
    company = get(data, "company", entity)
    deal = deal_of(event, data, entity)
    values = dict(values_of(event))
    if "amount" in values and deal and price(deal.get("plan")):
        # The fewest locations the amount could buy (at list price; any discount means more).
        values["locations_implied"] = values["amount"] / price(deal.get("plan"))
    tr = transcript_of(data, (deal or {}).get("id"))
    deal_view = None
    if deal:
        roles = [(get(data, "contact", c) or {}).get("role") for c in deal.get("contact_ids") or []]
        deal_view = {**deal, "contact_roles": [r for r in roles if r]}
    return {
        "action": event.get("action"),
        "catalog_action": event.get("catalog_action") or event.get("action"),
        "app": event.get("app"),
        "write": gate,
        "irreversible": bool(event.get("irreversible")),
        "ctx": event.get("ctx") or {},
        "args": event.get("args") or {},
        "values": values,
        "entity": entity,
        "company": {**company, "segments": segments(company)} if company else None,
        "deal": deal_view,
        "offer": offer_of(event, data),
        "run": run or {},
        "facts": facts_mod.deal_facts(tr.get("body") or "") if tr else {},
        "policy": cc["policy"],
        "actions": cc["actions"],
        "history": [
            {
                "action": e.get("action"),
                "catalog_action": e.get("catalog_action"),
                "app": e.get("app"),
                "ctx": e.get("ctx") or {},
                "object": e.get("object"),
            }
            for e in applied(history)
        ],
    }


def fact_inputs(
    event: dict[str, Any],
    history: list[dict[str, Any]],
    data: dict[str, Any] | None,
    view: dict[str, Any],
) -> dict[str, Any]:
    """What the fact check needs for one candidate step."""
    cc = company_context()
    srcs = sources(history, data, candidate=event)
    deal = view.get("deal")
    primary = next(
        (
            s["id"]
            for s in srcs
            if s["kind"] == cc["facts"]["primary_kind"] and deal and s["deal"] == deal["id"]
        ),
        None,
    )
    offers = run_offers(history, data, deal)
    rep_max = cc["policy"]["max_discount_rep"]
    discounts = {0.0} | {
        float(_num(o.get("discount_pct")) or 0)
        for o in offers
        if (_num(o.get("discount_pct")) or 0) <= rep_max or o.get("status") == "approved"
    }
    plans = sorted({p for p in [(deal or {}).get("plan")] + [o.get("plan") for o in offers] if p})
    resolve = cc["actions"]["resolves_conflict"]
    resolutions = [
        i
        for i, e in enumerate(applied(history))
        if is_write(e) and holds({"action": e.get("action"), "ctx": e.get("ctx") or {}}, resolve)
    ]
    return {
        "sources": srcs,
        "entity": view.get("entity"),
        "entity_names": {c["id"]: c.get("name") for c in (data or {}).get("companies") or []},
        "primary": primary,
        "plans": plans,
        "discounts": sorted(discounts),
        "resolutions": resolutions,
        "draft": (event.get("action") in cc["actions"]["drafts"]),
    }
