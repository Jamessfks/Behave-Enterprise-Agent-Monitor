"""check_step(): run the three checks on one agent step, before it executes. Stateless.

The caller (the browser, or the live agent loop) holds the run: it sends the history so far,
the step about to happen, the company context, and the running CUSUM, and gets back one verdict.
That keeps the server stateless, so it runs the same locally and on Vercel.
"""

from __future__ import annotations

import json
import time
from functools import cache
from pathlib import Path
from typing import Any

from env.company import default_context
from monitor.catalog import load_catalog
from monitor.events import load_run
from monitor.facts import check_facts
from monitor.normal import BlendRanker, NormalCheck
from monitor.rankers import BehaviorGPTRanker, WorkflowRanker
from monitor.rules import check_rules

ROOT = Path(__file__).resolve().parent.parent
CAL_PATH = Path(__file__).resolve().parent / "calibration.json"


def approved_runs() -> list[list[dict[str, Any]]]:
    return [load_run(p) for p in sorted((ROOT / "runs").glob("careful_*.jsonl"))]


@cache
def calibration() -> dict[str, Any]:
    return json.loads(CAL_PATH.read_text())


@cache
def _bgpt() -> BehaviorGPTRanker:
    return BehaviorGPTRanker()


@cache
def checks() -> dict[str, NormalCheck]:
    cal = calibration()["rankers"]
    bgpt = _bgpt()
    wf = WorkflowRanker(approved_runs())
    rankers = {"workflow": wf}
    if "behaviorgpt" in cal:
        rankers["behaviorgpt"] = bgpt
    if "blend" in cal:
        rankers["blend"] = BlendRanker(bgpt, wf, cal["blend"]["beta"])
    return {k: NormalCheck(r, cal[k], bgpt=bgpt) for k, r in rankers.items()}


def default_ranker() -> str:
    return calibration()["default"]


def _name(aid: str | None) -> str:
    cat = load_catalog()
    return cat[aid].name if aid in cat else (aid or "")


def _short(aid: str | None) -> str:
    """A short label for UI: the catalog name without trailing detail."""
    name = _name(aid)
    return name[0].upper() + name[1:] if name else ""


def fmt_p(p: float | None) -> str:
    if p is None:
        return "n/a"
    return "<0.1%" if p < 0.001 else f"{p:.1%}"


def check_step(
    history: list[dict[str, Any]],
    event: dict[str, Any],
    context: dict[str, Any] | None = None,
    cusum: float = 0.0,
    ranker: str | None = None,
) -> dict[str, Any]:
    ctx = context or default_context()
    ranker = ranker if ranker in checks() else default_ranker()
    normal = checks()[ranker]
    t0 = time.perf_counter()
    nv = normal.evaluate(history, event, cusum)
    t1 = time.perf_counter()
    fv = check_facts(history, event, ctx.get("pricing", {}).get("per_seat_month", {}))
    t2 = time.perf_counter()
    failed = [k for k, ok in (("normal", nv.ok), ("facts", fv.ok)) if not ok]
    rv = check_rules(history, event, ctx, checks_failed=failed)
    t3 = time.perf_counter()
    if not rv.ok:
        failed.append("rules")

    reasons: list[str] = []
    headline = ""
    missing: list[str] = []
    if nv.status == "scored":
        wf = checks()["workflow"].ranker
        missing = [_short(b) for b, _ in wf.missing(history, event["action_id"])[:3]]
        if not nv.ok:
            exp = nv.expected[0][0] if nv.expected else None
            headline = (
                f"Expected “{_short(exp)}”; actual “{_short(event['action_id'])}” "
                f"(p = {fmt_p(nv.p)})."
            )
            reasons.append(headline)
            if missing:
                reasons.append("Usually comes after: " + "; ".join(missing) + ".")
    reasons += fv.reasons + rv.reasons
    if not headline and reasons:
        headline = reasons[0]

    verdict = "pass" if not failed else "pause"
    precedent = None
    if failed and rv.precedents:
        covered = set()
        for r in ctx.get("learned_rules") or []:
            if r["id"] in {p.rule_id for p in rv.precedents}:
                covered |= set(r.get("checks") or failed)
        if set(failed) <= covered:
            verdict = "allowed_by_rule"
            precedent = rv.precedents[0].text

    return {
        "step": event.get("step"),
        "type": event["type"],
        "action_id": event.get("action_id"),
        "name": _short(event.get("action_id")) if event["type"] == "view" else None,
        "query": event.get("query"),
        "app": (event.get("details") or {}).get("app"),
        "irreversible": bool((event.get("details") or {}).get("irreversible")),
        "verdict": verdict,
        "failed": failed,
        "headline": headline,
        "reasons": reasons,
        "precedent": precedent,
        "ranker": ranker,
        "checks": {
            "normal": {
                "ok": nv.ok,
                "status": nv.status,
                "p": nv.p,
                "rank": nv.rank,
                "u": nv.u,
                "cusum": nv.cusum,
                "risk": nv.risk,
                "barrier": normal.barrier,
                "expected": [{"action_id": a, "name": _short(a), "p": p} for a, p in nv.expected],
                "missing": missing,
                "behaviorgpt": {
                    "rank": nv.bgpt_rank,
                    "of": len(load_catalog()),
                    "top": [{"action_id": a, "name": _short(a)} for a in nv.bgpt_top],
                },
            },
            "facts": {
                "ok": fv.ok,
                "checked": fv.checked,
                "warnings": fv.warnings,
            },
            "rules": {
                "ok": rv.ok,
                "violations": [r.__dict__ for r in rv.violations],
                "precedents": [r.__dict__ for r in rv.precedents],
            },
        },
        "latency_ms": {
            "normal": round((t1 - t0) * 1000, 2),
            "facts": round((t2 - t1) * 1000, 2),
            "rules": round((t3 - t2) * 1000, 2),
        },
    }


def learned_rule(event: dict[str, Any], failed: list[str], reason: str) -> dict[str, Any]:
    """The rule a person's Allow-with-reason becomes (check 3 applies it to later steps)."""
    entity = (event.get("details") or {}).get("entity")
    return {
        "id": f"learned.{event.get('action_id')}.{int(time.time() * 1000) % 10**8}",
        "kind": "precedent",
        "text": reason.strip(),
        "author": "You",
        "action_id": event.get("action_id"),
        "entity": entity,
        "checks": list(failed),
    }
