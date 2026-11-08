"""The monitor at the workspace's gate (ADR 0005): one call per agent step, before it counts.

The workspace calls `check()` from `workspace/monitor.py` for every agent write (gate=True,
may pause or block) and every agent read (gate=False, never pauses: a failed check is a flag).
This module only adapts workspace events and data (monitor/adapter.py) and runs the three
checks (monitor/core.py). It never imports `workspace`.
"""

from __future__ import annotations

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
        },
        cusum,
    )
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
