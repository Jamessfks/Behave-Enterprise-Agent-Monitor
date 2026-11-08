"""Record approved runs (training data for the company-workflow step model) and eval runs.

Runs the teammate's scripted agents (scenarios/http_runner.py) in-process against the workspace,
as the agent, with the monitor OFF (MONITOR_MODE=off): they're the company's "known good" work.

    uv run python scripts/make_runs.py --seed 1

Writes raw workspace events (one JSON per line; the monitor's adapter is applied when loading):
- runs/approved/: the careful Acme after-call run, baseline runs of agents C (follow-up and
  quote) and A (CRM autopilot) on the other accounts, and careful runs of the Bluepeak deep-dive
  scenario (world/scenarios/bluepeak_deep_dive.json: its common + careful steps; after the first
  run, the careful look-ups before the first write come in a shuffled order)
- runs/eval/: the Acme run with planted mistakes (used to check calibration, never to train)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path

os.environ["MONITOR_MODE"] = "off"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from scenarios import http_runner
from workspace import events
from workspace.main import create_app

APPROVED = ROOT / "runs" / "approved"
EVAL = ROOT / "runs" / "eval"
SCENARIOS = ROOT / "world" / "scenarios"
REF = re.compile(r"\$\{([a-z0-9_]+)\.([a-z0-9_]+)\}")


def record(path: Path, fn) -> int:
    try:
        fn()
    except http_runner.Blocked:
        pass
    evs = [e for e in events.EVENTS if e.get("app") != "ui"]
    path.write_text("".join(json.dumps(e) + "\n" for e in evs))
    return len(evs)


def _fill(value, saved: dict):
    """${name.field} -> that field of the response saved as `name` (scenario format, ADR 0009)."""
    if isinstance(value, str):
        return REF.sub(lambda m: str(saved[m.group(1)][m.group(2)]), value)
    if isinstance(value, list):
        return [_fill(v, saved) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, saved) for k, v in value.items()}
    return value


def scenario_careful(scenario_id: str, rng: random.Random | None = None) -> None:
    """A demo scenario's common + careful steps (world/scenarios/<id>.json), run as the agent.

    With `rng`, the careful look-ups between the shared reads and the first write are shuffled:
    a careful agent may check the contacts and the calendar in any order before it acts."""
    sc = json.loads((SCENARIOS / f"{scenario_id}.json").read_text())
    careful = list(sc["careful"])
    first_write = next((i for i, s in enumerate(careful) if s["method"] != "GET"), len(careful))
    checks = careful[:first_write]
    if rng is not None:
        rng.shuffle(checks)
    account = (sc.get("account_id") or "").removeprefix("co_") or None
    http_runner.reset(sc.get("agent", "C"), account, f"{scenario_id}: careful")
    saved: dict = {}
    for step in sc["common"] + checks + careful[first_write:]:
        path = _fill(step["path"], saved)
        if step["method"] == "GET":
            out = http_runner.get(path, **(step.get("query") or {}))
        else:
            out = http_runner.post(path, **_fill(step.get("body") or {}, saved))
        if step.get("save_as"):
            saved[step["save_as"]] = out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--n-c", type=int, default=12, help="baseline runs of agent C")
    ap.add_argument("--n-a", type=int, default=8, help="baseline runs of agent A")
    ap.add_argument("--n-b", type=int, default=3, help="careful runs of the Bluepeak scenario")
    a = ap.parse_args()
    random.seed(a.seed)
    for d in (APPROVED, EVAL):
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.jsonl"):
            f.unlink()
    http_runner.UI = False
    with TestClient(create_app(), headers={"X-Actor": "agent"}) as client:
        http_runner.C = client
        n = record(APPROVED / "acme_careful.jsonl", lambda: http_runner.acme_after_call(True))
        print(f"acme_careful: {n} events")
        for i in range(a.n_c):
            n = record(APPROVED / f"c_{i:02d}.jsonl", lambda: http_runner.baseline_one("C"))
            print(f"c_{i:02d}: {n} events")
        for i in range(a.n_a):
            n = record(APPROVED / f"a_{i:02d}.jsonl", lambda: http_runner.baseline_one("A"))
            print(f"a_{i:02d}: {n} events")
        # Own RNG, so the C and A baselines above draw exactly what they drew before.
        rng = random.Random(a.seed)
        for i in range(a.n_b):
            name = "bluepeak_careful" + (f"_{i:02d}" if i else "")
            n = record(
                APPROVED / f"{name}.jsonl",
                lambda i=i: scenario_careful("bluepeak_deep_dive", rng if i else None),
            )
            print(f"{name}: {n} events")
        http_runner.CONTINUE = True
        n = record(EVAL / "acme_mistakes.jsonl", lambda: http_runner.acme_after_call(False))
        print(f"eval acme_mistakes: {n} events")


if __name__ == "__main__":
    main()
