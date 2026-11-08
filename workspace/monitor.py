"""The monitor hook: every agent step is checked here before it counts (ADR 0005).

MONITOR_MODE
  agent (default) -> the three checks in-process (monitor/workspace_gate.py): step model,
                     fact check, rules check. Writes may pause/block; reads are scored only.
  off             -> always allow (used to record approved training runs)

APPROVE_EXTERNAL_SENDS=1 -> every email/quote/invite to someone outside shiftpoint.io pauses for a
                            person (PDF: "a person approves before it is sent"), unless already blocked.
"""

import os
from typing import Dict, List


def check(event: dict, history: List[dict], run: dict, run_state: dict, *, gate: bool) -> Dict:
    v = _check(event, history, run, run_state, gate=gate)
    if (gate and os.getenv("APPROVE_EXTERNAL_SENDS") == "1" and v.get("decision") in ("allow", "flag")
            and event.get("irreversible") and event.get("ctx", {}).get("recipient") not in (None, "internal")):
        return {**v, "decision": "pause", "reason": (v.get("reason") or "External send") + " - waiting for a person to approve"}
    return v


def _check(event: dict, history: List[dict], run: dict, run_state: dict, *, gate: bool) -> Dict:
    if os.getenv("MONITOR_MODE", "agent") == "off":
        return {"decision": "allow"}
    from monitor import workspace_gate  # local import: the monitor package never imports workspace

    from . import events, store

    return workspace_gate.check(event, history, run, run_state, store.DATA, events.LEARNED, gate=gate)
