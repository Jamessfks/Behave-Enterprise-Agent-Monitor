"""Go/no-go: where does BehaviorGPT rank the action that actually came next?

    uv run python -m monitor.go_no_go

Writes results/go_no_go.json. See .claude/skills/go-no-go/SKILL.md for the verdict rule.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from dotenv import load_dotenv

from monitor.catalog import load_catalog
from monitor.events import load_run
from monitor.rankers import BehaviorGPTRanker

ROOT = Path(__file__).resolve().parent.parent


def ranks_for_run(ranker, events):
    seen, rows = set(), []
    for i, e in enumerate(events):
        if e["type"] != "view" or e["action_id"] in seen:
            if e["type"] == "view":
                seen.add(e["action_id"])
            continue
        scores = ranker.rank(events[:i])
        order = sorted(scores, key=scores.get, reverse=True)
        rank = order.index(e["action_id"]) + 1 if e["action_id"] in scores else None
        rows.append({"step": i, "action_id": e["action_id"], "rank": rank, "top3": order[:3]})
        seen.add(e["action_id"])
    return rows


def main() -> None:
    load_dotenv(ROOT / ".env")
    ranker = BehaviorGPTRanker()
    cat = load_catalog()
    out = {"catalog_size": len(cat), "runs": {}}
    for path in sorted((ROOT / "runs").glob("*.jsonl")):
        rows = ranks_for_run(ranker, load_run(path))
        out["runs"][path.stem] = rows
        ranks = [r["rank"] for r in rows if r["rank"]]
        print(
            f"\n{path.stem}: median rank {statistics.median(ranks)}, top-5 share "
            f"{sum(r <= 5 for r in ranks) / len(ranks):.0%}"
        )
        for r in rows:
            print(f"  {r['step']:>2} {r['action_id']:<38} rank {r['rank']:>3}  top3 {r['top3']}")
    careful = [r["rank"] for k, v in out["runs"].items() if k.startswith("careful") for r in v]
    out["careful_median_rank"] = statistics.median(careful)
    out["careful_top5_share"] = sum(r <= 5 for r in careful) / len(careful)
    out["api_calls"], out["cache_hits"] = ranker.calls, ranker.cache_hits
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "go_no_go.json").write_text(json.dumps(out, indent=2) + "\n")
    print(
        f"\ncareful median rank {out['careful_median_rank']}, "
        f"top-5 share {out['careful_top5_share']:.0%} of {len(cat)} actions; "
        f"{ranker.calls} API calls"
    )


if __name__ == "__main__":
    main()
