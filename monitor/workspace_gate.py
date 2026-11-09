"""The monitor at the workspace's gate (ADR 0005): one call per agent step, before it counts.

The workspace calls `check()` from `workspace/monitor.py` for every agent write (gate=True,
may pause or block) and every agent read (gate=False, never pauses: a failed check is a flag).
This module only adapts workspace events and data (monitor/adapter.py) and runs the three
checks (monitor/core.py). It never imports `workspace`.
"""

from __future__ import annotations

import os
import time
from typing import Any

from monitor import adapter, core


def check(
    event: dict[str, Any],
    history: list[dict[str, Any]],
    run: dict[str, Any],
    run_state: dict[str, Any],
    data: dict[str, Any],
    learned: list[dict[str, Any]],
    *,
    gate: bool,
) -> dict[str, Any]:
    """Check one candidate workspace event (not yet applied; `before` holds the object).

    history: the run's workspace events so far (all layers; filtered here). run_state: the
    run's monitor memory; "cusum" is read and updated here. data: the workspace store (read
    only). learned: rules people taught ({id, decision, catalog_action, ctx, checks, reason, by}).
    Returns {decision, score, reason, failed, headline, reasons, checks, step, ranker,
    precedent, entity, latency_ms}.
    """
    t0 = time.perf_counter()
    steps = adapter.steps(history, data)
    step = adapter.to_step(event, data, len(steps))
    view = adapter.rule_view(event, history, data, run, gate=gate)
    inputs = adapter.fact_inputs(event, history, data, view)
    normal, ranker = core.normal_check(None)
    cusum = float(run_state.get("cusum") or 0.0)
    t1 = time.perf_counter()
    res = core.check_step(
        steps,
        step,
        {
            "normal": normal,
            "ranker": ranker,
            "facts": inputs,
            "view": view,
            "learned": learned,
            "data": data,
            # Live computer-use runs get the warm-started BehaviorGPT (ADR 0013); demo runs don't.
            "live": run.get("agent") == "computer_use",
        },
        cusum,
    )
    if gate and run.get("agent") == "computer_use":
        _behaviorgpt_judge(res)
    failed = res["failed"]
    if res["verdict"] == "pass" or res["verdict"] == "allowed_by_rule":
        decision = "allow"
    elif not gate:
        decision = "flag"
    else:
        decision = "block" if res["blocking"] else "pause"
    # Like an Allow/Block, any failed check starts the CUSUM afresh (normal.run_cusum).
    run_state["cusum"] = 0.0 if failed else float(res["checks"]["normal"]["cusum"] or 0.0)

    if res["verdict"] == "allowed_by_rule":
        reason = f"Allowed by precedent: {res['precedent']}"
    elif failed:
        reason = res["headline"]
    else:
        reason = ""
    risk = res["checks"]["normal"]["risk"]
    score = 1.0 if failed else (round(min(1.0, risk), 3) if risk is not None else None)
    latency = dict(res["latency_ms"])
    latency["adapter"] = round((t1 - t0) * 1000, 2)
    latency["total"] = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "decision": decision,
        "score": score,
        "reason": reason,
        "failed": failed,
        "headline": res["headline"],
        "reasons": res["reasons"],
        "checks": res["checks"],
        "step": res["step"],
        "ranker": ranker,
        "precedent": res["precedent"],
        "entity": res["entity"],
        "action_id": res["action_id"],
        "name": res["name"],
        "latency_ms": latency,
    }


def _behaviorgpt_judge(res: dict[str, Any]) -> None:
    """Live computer use only (ADR 0013): BehaviorGPT also judges every change the agent tries.
    Ranked outside its top LIVE_BGPT_CUTOFF (default 8) of the catalog, the change is held for a
    person and the agent stops until they decide. On the approved runs this cutoff caught 4 of
    the 5 planted mistakes and held 22 of 86 correct changes. Demo runs never get here."""
    b = (res["checks"]["normal"] or {}).get("behaviorgpt") or {}
    rank, cutoff = b.get("rank"), int(os.environ.get("LIVE_BGPT_CUTOFF", "8"))
    if not rank or rank <= cutoff or res["verdict"] == "allowed_by_rule":
        return
    expected = ", ".join(f"“{t['name']}”" for t in (b.get("top") or [])[:3])
    headline = f"BehaviorGPT: unusual step. It ranked this #{rank} of {b.get('of')}" + (
        f"; it expected {expected}." if expected else "."
    )
    res["failed"] = [*res["failed"], "behaviorgpt"]
    res["reasons"] = [headline, *res["reasons"]]
    if res["verdict"] in ("pass", "allowed_by_rule"):
        res["verdict"] = "pause"
        res["headline"] = headline
