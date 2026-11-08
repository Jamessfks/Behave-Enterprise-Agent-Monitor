"""Scripted demo runs that execute against the real workspace, one step at a time (ADR 0009).

A scenario is data (`world/scenarios/<id>.json`): shared `common` steps, then either the
`careful` or the `mistakes` steps. Each step is one HTTP call the agent makes. Steps may
reference earlier responses as `${name.field}` (e.g. the id of a quote created earlier).

The runner's progress lives in `events.RUN_STATE["scenario"]`, which is part of the workspace
snapshot, so it survives between requests and Vercel instances.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from workspace import changes, dispatch, events, store

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "world" / "scenarios"
REF = re.compile(r"\$\{([a-z0-9_]+)\.([a-z0-9_]+)\}")
APP_NAMES = {
    "jmail": "Jmail",
    "jdrive": "Jdrive",
    "habspot": "Habspot",
    "calendar": "Calendario",
    "quote": "Quotes",
}
PAGE_APPS = (
    ("/mail", "Jmail"),
    ("/drive", "Jdrive"),
    ("/crm", "Habspot"),
    ("/calendar", "Calendario"),
)
SKIP_APPS = ("ui", "session", "sentinel")
SIDE_ACTIONS = ("jmail.attach", "quote.discount")


def load(scenario_id: str) -> dict[str, Any]:
    path = SCENARIOS / f"{scenario_id}.json"
    if not path.exists():
        raise KeyError(f"unknown scenario {scenario_id!r}")
    return json.loads(path.read_text())


def scenarios() -> list[dict[str, Any]]:
    """Every demo task in world/scenarios, for the picker."""
    out = []
    for path in sorted(SCENARIOS.glob("*.json")):
        sc = json.loads(path.read_text())
        out.append(
            {
                "id": sc["id"],
                "title": sc["title"],
                "short": sc.get("short") or sc["title"],
                "account": sc.get("account", ""),
                "request": sc.get("request", ""),
            }
        )
    return out


def steps_for(scenario: dict[str, Any], mistakes: bool) -> list[dict[str, Any]]:
    return scenario["common"] + scenario["mistakes" if mistakes else "careful"]


def start(scenario_id: str, mistakes: bool) -> dict[str, Any]:
    """Reset the world to the seed and start a run of this scenario."""
    sc = load(scenario_id)
    store.reset()
    label = f"{sc['title']} ({'with' if mistakes else 'without'} planted mistakes)"
    run = events.start_run(
        agent=sc.get("agent", "C"), account_id=sc.get("account_id"), actor="agent", label=label
    )
    events.RUN_STATE["scenario"] = {
        "id": scenario_id,
        "mistakes": mistakes,
        "cursor": 0,
        "total": len(steps_for(sc, mistakes)),
        "saved": {},
        "steps": [],
        "awaiting": None,
    }
    store.save()
    return {
        "run": {**run, "scenario": scenario_id, "mistakes": mistakes, "live": False},
        "steps_total": events.RUN_STATE["scenario"]["total"],
        "upcoming": upcoming(),
    }


def _resolve(value: Any, saved: dict[str, Any]) -> Any:
    """Fill ${name.field} references from earlier responses. Missing ones stay unresolved."""
    if isinstance(value, str):
        return REF.sub(
            lambda m: str((saved.get(m.group(1)) or {}).get(m.group(2), m.group(0))), value
        )
    if isinstance(value, list):
        return [_resolve(v, saved) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, saved) for k, v in value.items()}
    return value


def _settle_awaiting(sc: dict[str, Any]) -> None:
    """After a person decided on a paused step, record what an approval created (e.g. a doc id)."""
    awaiting = sc.get("awaiting")
    if not awaiting or awaiting["approval_id"] in events.PENDING:
        return
    replayed = next(
        (e for e in reversed(events.EVENTS) if e.get("approval_id") == awaiting["approval_id"]),
        None,
    )
    if replayed and awaiting.get("save_as") and replayed.get("object"):
        sc["saved"][awaiting["save_as"]] = {
            "doc_id": replayed["object"]["id"],
            "id": replayed["object"]["id"],
        }
    decided = next(
        (
            e
            for e in reversed(events.EVENTS)
            if e.get("action") in ("sentinel.approved", "sentinel.rejected")
            and (e.get("args") or {}).get("approval_id") == awaiting["approval_id"]
        ),
        None,
    )
    args = (decided or {}).get("args") or {}
    for step in sc["steps"]:
        if step.get("approval_id") == awaiting["approval_id"]:
            step["resolution"] = {
                "decision": "allow" if replayed else "block",
                "reason": args.get("reason", ""),
            }
            step["changes"] = args.get("changes") or []
    sc["awaiting"] = None


def step_view(
    ev: dict[str, Any] | None, spec: dict[str, Any], index: int, page: str
) -> dict[str, Any]:
    """One step as the canvas shows it (contract in docs/event-schema.md)."""
    from monitor.catalog import load_catalog

    kind = "write" if spec["method"] != "GET" else "read"
    if ev and ev.get("action", "").endswith(".search"):
        kind = "search"
    monitor = (ev or {}).get("monitor") or {}
    decision = (ev or {}).get("decision", "allow")
    cat = load_catalog()
    ca = (ev or {}).get("catalog_action")
    return {
        "index": index,
        "label": spec["label"],
        "app": APP_NAMES.get((ev or {}).get("app", ""), "Habspot"),
        "page": page,
        "kind": kind,
        "action": (ev or {}).get("action"),
        "catalog_action": ca,
        "name": cat[ca].name if ca in cat else spec["label"],
        "values": (ev or {}).get("args") or {},
        "decision": decision,
        "approval_id": (ev or {}).get("pending_approval_id"),
        "planted": bool(spec.get("planted")),
        "event_id": (ev or {}).get("id"),
        "look_for": spec.get("look_for") or [],
        "changes": [],
        "check": {
            "verdict": {"allow": "pass", "flag": "flag", "pause": "pause", "block": "block"}.get(
                decision, decision
            ),
            "failed": monitor.get("failed", []),
            "headline": monitor.get("headline", ""),
            "reasons": monitor.get("reasons", []),
            "precedent": monitor.get("precedent"),
            "ranker": monitor.get("ranker"),
            "checks": monitor.get("checks", {}),
            "latency_ms": monitor.get("latency_ms", {}),
        },
    }


def _step_event(new_events: list[dict[str, Any]]) -> dict[str, Any] | None:
    meaningful = [
        e
        for e in new_events
        if e.get("app") not in SKIP_APPS and e.get("action") not in SIDE_ACTIONS
    ]
    return meaningful[-1] if meaningful else None


async def next_step(app: FastAPI) -> dict[str, Any]:
    sc = events.RUN_STATE.get("scenario")
    if not sc:
        return {"done": True, "step": None, "changed": changed()}
    _settle_awaiting(sc)
    if sc.get("awaiting"):
        return {
            "done": False,
            "waiting": sc["awaiting"],
            "step": None,
            "changed": changed(),
            "upcoming": None,
        }
    spec_list = steps_for(load(sc["id"]), sc["mistakes"])
    if sc["cursor"] >= len(spec_list):
        return {"done": True, "step": None, "changed": changed()}

    spec = spec_list[sc["cursor"]]
    index = sc["cursor"]
    sc["cursor"] += 1
    saved = sc["saved"]
    path = _resolve(spec["path"], saved)
    body = _resolve(spec.get("body"), saved)
    query = spec.get("query") or ""
    if "${" in path or "${" in json.dumps(body or {}):
        view = step_view(None, spec, index, "")
        view.update(
            decision="skipped",
            check={
                **view["check"],
                "verdict": "skipped",
                "headline": "Skipped: it depends on an earlier step that didn't happen.",
            },
        )
        sc["steps"].append(view)
        store.save()
        return {
            "done": sc["cursor"] >= len(spec_list),
            "step": view,
            "changed": changed(),
            "upcoming": upcoming(),
        }

    before = len(events.EVENTS)
    status, out, diff = await call_with_changes(app, spec["method"], path, body, query)
    ev = _step_event(events.EVENTS[before:])
    if spec.get("save_as") and status < 300 and isinstance(out, dict):
        saved[spec["save_as"]] = out
    approval_id = None
    if status == 202 and isinstance(out, dict):
        approval_id = (out.get("detail") or {}).get("approval_id")
        sc["awaiting"] = {"approval_id": approval_id, "save_as": spec.get("save_as")}
    if ev is not None and approval_id:
        ev["pending_approval_id"] = approval_id
    page = _resolve(spec.get("page") or "", saved)
    view = step_view(ev, spec, index, page if "${" not in page else "")
    if approval_id:
        view["approval_id"] = approval_id
    view["changes"] = diff
    if status >= 400 and status != 403:
        view["decision"] = "error"
        view["check"]["headline"] = (
            f"The app answered {status}: {(out or {}).get('detail') if isinstance(out, dict) else out}"
        )
    sc["steps"].append(view)
    store.save()
    return {
        "done": sc["cursor"] >= len(spec_list) and not sc.get("awaiting"),
        "step": view,
        "changed": changed(),
        "upcoming": upcoming(),
    }


async def call_with_changes(
    app: FastAPI, method: str, path: str, body: Any = None, query: Any = ""
) -> tuple[int, Any, list[dict[str, Any]]]:
    """One agent call; for a write, also what it changed in the apps (workspace/changes.py)."""
    before = changes.capture() if method != "GET" else None
    status, out = await dispatch.call(app, method, path, body, query)
    return status, out, changes.diff(before, store.DATA) if before is not None else []


def app_of_page(page: str) -> str:
    return next((name for prefix, name in PAGE_APPS if page.startswith(prefix)), "")


def upcoming() -> dict[str, Any] | None:
    """The next step, before it runs: the canvas opens its page first so the app shows the
    'before' state, then asks the server to run (and check) it."""
    sc = events.RUN_STATE.get("scenario")
    if not sc or sc.get("awaiting"):
        return None
    specs = steps_for(load(sc["id"]), sc["mistakes"])
    if sc["cursor"] >= len(specs):
        return None
    spec = specs[sc["cursor"]]
    page = _resolve(spec.get("before_page") or spec.get("page") or "", sc["saved"])
    page = "" if "${" in page else page
    return {
        "index": sc["cursor"],
        "label": spec["label"],
        "kind": "write" if spec["method"] != "GET" else "read",
        "page": page,
        "app": app_of_page(page),
    }


def current() -> dict[str, Any]:
    sc = events.RUN_STATE.get("scenario") or {}
    if sc:
        _settle_awaiting(sc)
    return {
        "run": {
            **events.RUN,
            "scenario": sc.get("id"),
            "mistakes": sc.get("mistakes"),
            "live": False,
        },
        "steps": sc.get("steps", []),
        "changed": changed(),
        "done": bool(sc) and sc.get("cursor", 0) >= sc.get("total", 0) and not sc.get("awaiting"),
        "waiting": sc.get("awaiting"),
        "upcoming": upcoming() if sc else None,
    }


def changed() -> list[dict[str, str]]:
    """Links to everything the agent's allowed writes changed, for the 'What changed' list."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for e in events.EVENTS:
        if e.get("by") != "agent" or e.get("decision") not in ("allow", "flag"):
            continue
        if e.get("app") in SKIP_APPS or e.get("action") in SIDE_ACTIONS:
            continue
        if e.get("action", "").split(".")[-1].startswith(("open", "search", "list")):
            continue
        for link in (_link(e), _doc_link(e)):
            if link and link["url"] not in seen:
                seen.add(link["url"])
                out.append(link)
    return out


def _doc_link(e: dict[str, Any]) -> dict[str, str] | None:
    """Writes that created or changed a document elsewhere (e.g. a quote created from a deal)."""
    doc_id = (e.get("args") or {}).get("doc_id")
    if not doc_id or (e.get("object") or {}).get("id") == doc_id:
        return None
    d = store.get("docs", doc_id) or {}
    return {"app": "Jdrive", "label": d.get("name", "Document"), "url": f"/drive/doc/{doc_id}"}


def _link(e: dict[str, Any]) -> dict[str, str] | None:
    o = e.get("object") or {}
    t, i = o.get("type"), o.get("id")
    action = e.get("action", "")
    if action.startswith("jmail.draft"):
        return {"app": "Jmail", "label": "Draft saved in Jmail", "url": "/mail?label=DRAFT"}
    if action.startswith(
        ("jmail.send", "jmail.reply", "jmail.forward", "quote.send", "quote.request_approval")
    ):
        return {"app": "Jmail", "label": "Sent mail in Jmail", "url": "/mail?label=SENT"}
    if t == "deal" or (t in ("note", "task", "activity") and (e.get("args") or {}).get("deal_id")):
        deal = i if t == "deal" else e["args"]["deal_id"]
        d = store.get("deals", deal) or {}
        return {
            "app": "Habspot",
            "label": f"Deal: {d.get('name', deal)}",
            "url": f"/crm/deal/{deal}",
        }
    if t == "doc" and i:
        d = store.get("docs", i) or {}
        return {"app": "Jdrive", "label": d.get("name", "Document"), "url": f"/drive/doc/{i}"}
    if t == "event" and i:
        ev = store.get("calendar", i) or {}
        return {
            "app": "Calendario",
            "label": ev.get("title", "Calendar event"),
            "url": f"/calendar/event/{i}",
        }
    if t == "contact" and i:
        return {"app": "Habspot", "label": "Contact", "url": f"/crm/contact/{i}"}
    return None
