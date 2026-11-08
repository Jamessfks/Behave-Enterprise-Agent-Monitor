"""check_step(): run the three checks on one agent step, before it executes. Stateless.

The caller holds the run and passes the step events so far, the step about to happen, and a
context built from the workspace (monitor/workspace_gate.py does this for workspace events):

- context["normal"]: the step model (a NormalCheck) or None when there are no approved runs;
- context["facts"]: the fact check's inputs (adapter.fact_inputs: opened sources, primary...);
- context["view"]: the rules check's view of the step (adapter.rule_view);
- context["learned"]: rules people taught by allowing or blocking with a reason.

BehaviorGPT ranks every step as evidence only (ADR 0004): its rank and top guesses are shown,
and it never changes a verdict.
"""

from __future__ import annotations

import json
import logging
import time
from functools import cache
from pathlib import Path
from typing import Any

from monitor import adapter
from monitor.context import ROOT, company_context
from monitor.facts import check_facts
from monitor.normal import NormalCheck, NormalVerdict
from monitor.rankers import BehaviorGPTRanker, WorkflowRanker
from monitor.rules import check_rules

log = logging.getLogger(__name__)
CAL_PATH = Path(__file__).resolve().parent / "calibration.json"


def _step_cfg() -> dict[str, Any]:
    return company_context()["step_model"]


def approved_dir() -> Path:
    return ROOT / _step_cfg()["approved_runs"]


@cache
def calibration() -> dict[str, Any]:
    return json.loads(CAL_PATH.read_text()) if CAL_PATH.exists() else {"rankers": {}}


def load_raw_run(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def approved_runs(directory: str | Path | None = None) -> list[list[dict[str, Any]]]:
    """The company's approved runs (raw workspace events) as step events."""
    d = Path(directory) if directory else approved_dir()
    runs = [adapter.steps(load_raw_run(p)) for p in sorted(d.glob("*.jsonl"))] if d.is_dir() else []
    return [r for r in runs if any(e["type"] == "view" for e in r)]


def catalog_ids() -> list[str]:
    try:
        from monitor.catalog import load_catalog

        return list(load_catalog())
    except (OSError, ValueError, KeyError) as e:  # the catalog is optional for the step model
        log.warning("catalog unavailable: %s", e)
        return []


def workflow_ranker(runs: list[list[dict[str, Any]]]) -> WorkflowRanker:
    """Dependencies learned from approved runs, over the catalog plus every action they used."""
    seen = [e["action_id"] for r in runs for e in r if e["type"] == "view"]
    return WorkflowRanker(runs, actions=list(dict.fromkeys(catalog_ids() + seen)))


@cache
def normal_check(directory: str | None = None) -> tuple[NormalCheck | None, str]:
    """The step model and its label. None (status "untrained") when there are no approved runs;
    default calibration (said so in the label) when calibration.json has no entry for it."""
    runs = approved_runs(directory)
    if not runs:
        return None, "workflow (untrained: no approved runs)"
    cfg = _step_cfg()
    cal = calibration().get("rankers", {}).get(cfg["calibration_key"])
    label = "workflow"
    if not cal or not all(k in cal for k in ("tau", "loc", "scale", "barrier")):
        cal = dict(cfg["default_calibration"])
        label = "workflow (default calibration: tau 1, loc 0, scale 1, barrier 6)"
    return NormalCheck(workflow_ranker(runs), cal), label


@cache
def bgpt() -> BehaviorGPTRanker | None:
    try:
        return BehaviorGPTRanker()
    except (OSError, ValueError, KeyError) as e:
        log.warning("BehaviorGPT ranker unavailable: %s", e)
        return None


def behaviorgpt_evidence(history: list[dict[str, Any]], event: dict[str, Any]) -> dict[str, Any]:
    """BehaviorGPT's rank of this step and its top guesses: evidence, never a vote."""
    out: dict[str, Any] = {"rank": None, "of": len(catalog_ids()), "top": []}
    b = bgpt()
    if event["type"] != "view" or b is None:
        return out
    try:
        if not (b.available or b.cached(history)):
            return out
        scores = b.rank(history)
        order = sorted(scores, key=scores.get, reverse=True)
        out["rank"] = order.index(event["action_id"]) + 1 if event["action_id"] in scores else None
        out["top"] = [{"action_id": a, "name": label(a)} for a in order[:3]]
    except Exception as e:  # noqa: BLE001 - evidence only: an outage never blocks the agent
        log.warning("BehaviorGPT unavailable for this step: %s", e)
    return out


def label(aid: str | None) -> str:
    """A short name for the UI: the catalog name, else the id made readable."""
    if not aid:
        return ""
    try:
        from monitor.catalog import load_catalog

        cat = load_catalog()
        if aid in cat:
            name = cat[aid].name
            return name[0].upper() + name[1:]
    except (OSError, ValueError, KeyError) as e:
        log.debug("catalog unavailable for labels: %s", e)
    base, *tags = aid.split(":")
    app, _, verb = base.partition(".")
    text = f"{app.capitalize()}: {verb.replace('_', ' ')}"
    return text + (f" ({', '.join(t.replace('_', ' ') for t in tags)})" if tags else "")


def fmt_p(p: float | None) -> str:
    if p is None:
        return "n/a"
    return "under 0.1%" if p < 0.001 else f"{p:.1%}"


def check_step(
    history: list[dict[str, Any]],
    event: dict[str, Any],
    context: dict[str, Any] | None = None,
    cusum: float = 0.0,
    ranker: str | None = None,
) -> dict[str, Any]:
    """The three checks on one step event (adapter.to_step), given the step events before it."""
    ctx = context or {}
    if "normal" in ctx:
        normal, ranker_label = ctx["normal"], ctx.get("ranker") or "workflow"
    else:
        normal, ranker_label = normal_check()
    barrier = normal.barrier if normal else _step_cfg()["default_calibration"]["barrier"]

    t0 = time.perf_counter()
    if normal is None:
        nv = NormalVerdict("untrained", cusum=cusum, risk=cusum / barrier)
    else:
        nv = normal.evaluate(history, event, cusum)
    tb = time.perf_counter()
    bg = behaviorgpt_evidence(history, event)
    t1 = time.perf_counter()
    fv = check_facts(event, ctx.get("facts"))
    t2 = time.perf_counter()
    failed = [k for k, ok in (("normal", nv.ok), ("facts", fv.ok)) if not ok]
    view = ctx.get("view") or {
        "action": (event.get("details") or {}).get("action"),
        "catalog_action": event.get("action_id"),
        "entity": (event.get("details") or {}).get("entity"),
        "values": (event.get("details") or {}).get("values") or {},
    }
    rv = check_rules(view, ctx.get("rules"), ctx.get("learned"), failed, ctx.get("data"))
    t3 = time.perf_counter()
    if not rv.ok:
        failed.append("rules")

    reasons: list[str] = []
    headline = ""
    missing: list[str] = []
    if nv.status == "scored" and isinstance(normal.ranker, WorkflowRanker):
        missing = [label(b) for b, _ in normal.ranker.missing(history, event["action_id"])[:3]]
    if nv.status == "scored" and not nv.ok:
        exp = nv.expected[0][0] if nv.expected else None
        headline = (
            f"Expected “{label(exp)}”; actual “{label(event['action_id'])}” ({fmt_p(nv.p)} likely)."
        )
        reasons.append(headline)
        if missing:
            reasons.append("Usually comes after: " + "; ".join(missing) + ".")
    reasons += fv.reasons + rv.reasons
    if not headline and reasons:
        headline = reasons[0]

    verdict = "pass" if not failed else "pause"
    precedent = None
    if failed and rv.precedents and set(failed) <= rv.covered and not rv.blocking:
        verdict = "allowed_by_rule"
        p = rv.precedents[0]
        precedent = f"{p.text} ({p.author})" if p.author else p.text

    details = event.get("details") or {}
    return {
        "step": event.get("step"),
        "type": event["type"],
        "action_id": event.get("action_id"),
        "name": label(event.get("action_id")) if event["type"] == "view" else None,
        "query": event.get("query"),
        "app": details.get("app"),
        "entity": details.get("entity"),
        "irreversible": bool(details.get("irreversible")),
        "verdict": verdict,
        "failed": failed,
        "blocking": rv.blocking,
        "headline": headline,
        "reasons": reasons,
        "precedent": precedent,
        "ranker": ranker_label,
        "checks": {
            "normal": {
                "ok": nv.ok,
                "status": nv.status,
                "p": nv.p,
                "rank": nv.rank,
                "u": nv.u,
                "cusum": nv.cusum,
                "risk": nv.risk,
                "barrier": barrier,
                "expected": [{"action_id": a, "name": label(a), "p": p} for a, p in nv.expected],
                "missing": missing,
                "behaviorgpt": bg,
            },
            "facts": {"ok": fv.ok, "checked": fv.checked, "warnings": fv.warnings},
            "rules": {
                "ok": rv.ok,
                "violations": [r.__dict__ for r in rv.violations],
                "precedents": [r.__dict__ for r in rv.precedents],
                "advisories": [r.__dict__ for r in rv.advisories],
            },
        },
        "latency_ms": {
            "normal": round((tb - t0) * 1000, 2),
            "behaviorgpt": round((t1 - tb) * 1000, 2),
            "facts": round((t2 - t1) * 1000, 2),
            "rules": round((t3 - t2) * 1000, 2),
        },
    }
