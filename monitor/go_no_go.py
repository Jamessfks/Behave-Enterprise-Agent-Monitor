"""Go/no-go: where does BehaviorGPT rank the action that actually came next? (ADR 0004)

    uv run python -m monitor.go_no_go

Runs over the approved runs (runs/approved/) and the eval run (runs/eval/), converted to step
events by the same adapter the gate uses, so every ranking it fetches is also the cache entry the
live gate will ask for (runs/rankings_cache.json, committed so replays need no API key).
Writes results/go_no_go.json.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from dotenv import load_dotenv

from monitor import adapter
from monitor.catalog import load_catalog
from monitor.events import load_run
from monitor.rankers import BehaviorGPTRanker

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "world" / "seed" / "state.json"


def ranks_for_run(ranker, steps):
    seen, rows = set(), []
    for i, e in enumerate(steps):
        if e["type"] != "view" or e["action_id"] in seen:
            if e["type"] == "view":
                seen.add(e["action_id"])
            continue
        scores = ranker.rank(steps[:i])
        order = sorted(scores, key=scores.get, reverse=True)
        rank = order.index(e["action_id"]) + 1 if e["action_id"] in scores else None
        rows.append({"step": i, "action_id": e["action_id"], "rank": rank, "top3": order[:3]})
        seen.add(e["action_id"])
    return rows


def main() -> None:
    load_dotenv(ROOT / ".env")
    ranker = BehaviorGPTRanker()
    cat = load_catalog()
    data = json.loads(SEED.read_text())
    out: dict = {"catalog_size": len(cat), "runs": {}}
    files = sorted((ROOT / "runs" / "approved").glob("*.jsonl")) + sorted(
        (ROOT / "runs" / "eval").glob("*.jsonl")
    )
    for path in files:
        steps = adapter.steps(load_run(path), data)
        rows = ranks_for_run(ranker, steps)
        out["runs"][f"{path.parent.name}/{path.stem}"] = rows
        ranks = [r["rank"] for r in rows if r["rank"]]
        if ranks:
            print(
                f"{path.parent.name}/{path.stem}: median rank {statistics.median(ranks)} "
                f"of {len(cat)}, top-5 share {sum(r <= 5 for r in ranks) / len(ranks):.0%}"
            )
    approved = [
        r["rank"]
        for k, v in out["runs"].items()
        if k.startswith("approved")
        for r in v
        if r["rank"]
    ]
    out["careful_median_rank"] = statistics.median(approved)
    out["careful_top5_share"] = sum(r <= 5 for r in approved) / len(approved)
    out["api_calls"], out["cache_hits"] = ranker.calls, ranker.cache_hits
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "go_no_go.json").write_text(json.dumps(out, indent=2) + "\n")
    print(
        f"\napproved runs: median rank {out['careful_median_rank']} of {len(cat)}, "
        f"top-5 share {out['careful_top5_share']:.0%}; {ranker.calls} API calls"
    )


if __name__ == "__main__":
    main()
