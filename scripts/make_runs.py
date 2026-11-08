"""Record approved runs (training data for the company-workflow step model) and eval runs.

Runs the teammate's scripted agents (scenarios/http_runner.py) in-process against the workspace,
as the agent, with the monitor OFF (MONITOR_MODE=off): they're the company's "known good" work.

    uv run python scripts/make_runs.py --seed 1

Writes raw workspace events (one JSON per line; the monitor's adapter is applied when loading):
- runs/approved/: the careful Acme after-call run, plus baseline runs of agents C (follow-up and
  quote) and A (CRM autopilot) on the other accounts
- runs/eval/: the Acme run with planted mistakes (used to check calibration, never to train)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

os.environ["MONITOR_MODE"] = "off"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from scenarios import http_runner  # noqa: E402
from workspace import events  # noqa: E402
from workspace.main import create_app  # noqa: E402

APPROVED = ROOT / "runs" / "approved"
EVAL = ROOT / "runs" / "eval"


def record(path: Path, fn) -> int:
    try:
        fn()
    except http_runner.Blocked:
        pass
    evs = [e for e in events.EVENTS if e.get("app") != "ui"]
    path.write_text("".join(json.dumps(e) + "\n" for e in evs))
    return len(evs)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--n-c", type=int, default=12, help="baseline runs of agent C")
    ap.add_argument("--n-a", type=int, default=8, help="baseline runs of agent A")
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
        http_runner.CONTINUE = True
        n = record(EVAL / "acme_mistakes.jsonl", lambda: http_runner.acme_after_call(False))
        print(f"eval acme_mistakes: {n} events")


if __name__ == "__main__":
    main()
