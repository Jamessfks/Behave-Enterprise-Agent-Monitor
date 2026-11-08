"""Audit: is BehaviorGPT really called, and what does it actually decide?

Forces live API calls (an empty cache, so nothing is served from runs/rankings_cache.json),
counts and times every `complete()` call at the SDK boundary, and checks:

1. live output vs the committed cache (are the cached rankings real API output?)
2. determinism (same history twice) and sensitivity (different histories, different answers)
3. the full monitor path: BehaviorGPT calls made while check_step() replays the faulty run
4. ablation: do verdicts change when BehaviorGPT is unavailable, or used as the ranker?

    uv run python scripts/audit_behaviorgpt.py      # needs UNBOXAI_API_KEY; ~150 API calls

Writes results/behaviorgpt_audit.json.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import behaviorgpt
from behaviorgpt import UnboxAIError

from monitor import core
from monitor.events import load_run
from monitor.rankers import BehaviorGPTRanker, RankingCache, history_key

CALLS: list[dict] = []
_real_complete = behaviorgpt.UnboxAIClient.complete


def counting_complete(self, history=(), limit=10, offset=0, **kw):
    t0 = time.perf_counter()
    res = _real_complete(self, history, limit, offset, **kw)
    CALLS.append(
        {
            "ms": round((time.perf_counter() - t0) * 1000, 1),
            "catalog_id": kw.get("catalog_id"),
            "history_len": len(history),
            "items": len(res.items),
        }
    )
    return res


behaviorgpt.UnboxAIClient.complete = counting_complete


def scored_prefixes(run):
    seen = set()
    for i, e in enumerate(run):
        if e["type"] == "view" and e["action_id"] not in seen:
            seen.add(e["action_id"])
            yield i, e


def rank_of(scores, aid):
    order = sorted(scores, key=scores.get, reverse=True)
    return order.index(aid) + 1, order[:3]


def replay(run, ranker, ctx=None):
    cusum, out = 0.0, []
    for i, e in enumerate(run):
        r = core.check_step(run[:i], e, ctx, cusum, ranker)
        out.append(r)
        cusum = 0.0 if r["verdict"] != "pass" else r["checks"]["normal"]["cusum"]
    return out


def main() -> None:
    report: dict = {}
    committed = RankingCache()  # runs/rankings_cache.json
    tmp = Path(tempfile.mkdtemp()) / "fresh.json"
    live = BehaviorGPTRanker(cache=RankingCache(tmp))  # empty: every rank() is a live call
    assert live.available, "UNBOXAI_API_KEY and UNBOXAI_CATALOG_ID must be set"
    report["catalog_id"] = live.catalog_id

    # 1. live vs committed cache, for every scored step of both demo runs
    rows, max_diff, same_order, compared = [], 0.0, 0, 0
    for name in ["careful_01", "faulty"]:
        run = load_run(ROOT / "runs" / f"{name}.jsonl")
        for i, e in scored_prefixes(run):
            scores = live.rank(run[:i])
            rank, top3 = rank_of(scores, e["action_id"])
            cached = committed.get(history_key(live.catalog_id, run[:i]))
            diff = None
            if cached:
                compared += 1
                diff = max(abs(scores[a] - cached.get(a, float("nan"))) for a in scores)
                max_diff = max(max_diff, diff)
                same_order += sorted(scores, key=scores.get) == sorted(cached, key=cached.get)
            rows.append(
                {
                    "run": name,
                    "step": i,
                    "action_id": e["action_id"],
                    "live_rank": rank,
                    "live_top3": top3,
                    "max_abs_diff_vs_cache": diff,
                }
            )
    report["live_vs_cache"] = {
        "steps": len(rows),
        "compared_with_cache": compared,
        "identical_ordering": same_order,
        "max_abs_score_diff": max_diff,
    }
    report["steps"] = rows
    n_after_1 = len(CALLS)

    # 2. determinism and sensitivity
    run = load_run(ROOT / "runs" / "faulty.jsonl")
    a = BehaviorGPTRanker(cache=RankingCache(Path(tempfile.mkdtemp()) / "a.json")).rank(run[:13])
    b = BehaviorGPTRanker(cache=RankingCache(Path(tempfile.mkdtemp()) / "b.json")).rank(run[:13])
    report["determinism_max_abs_diff"] = max(abs(a[k] - b[k]) for k in a)
    tops = {}
    for cut in (1, 7, 15):
        s = live.rank(run[:cut])
        tops[f"after_{cut}_events"] = rank_of(s, next(iter(s)))[1]
    report["sensitivity_top3"] = tops
    report["distinct_top3"] = len({tuple(v) for v in tops.values()})

    # 3. the real monitor path, with an empty cache: how many live calls does a replay make?
    core._bgpt().cache = RankingCache(Path(tempfile.mkdtemp()) / "core.json")
    before = len(CALLS)
    default_results = replay(run, None)
    report["monitor_replay"] = {
        "default_ranker": core.default_ranker(),
        "scored_steps": sum(r["checks"]["normal"]["status"] == "scored" for r in default_results),
        "live_calls": len(CALLS) - before,
        "bgpt_rank_shown": [r["checks"]["normal"]["behaviorgpt"]["rank"] for r in default_results],
    }

    # 4. ablation: verdicts with BehaviorGPT down, and with BehaviorGPT deciding
    def verdicts(results):
        return [
            (i, r["action_id"], r["verdict"], r["failed"])
            for i, r in enumerate(results)
            if r["verdict"] != "pass"
        ]

    def broken(self, *a, **k):
        raise UnboxAIError("audit: BehaviorGPT disabled", status_code=503)

    core._bgpt().cache = RankingCache(Path(tempfile.mkdtemp()) / "off.json")
    behaviorgpt.UnboxAIClient.complete = broken
    off = replay(run, "workflow")
    behaviorgpt.UnboxAIClient.complete = counting_complete
    report["ablation"] = {
        "workflow_with_behaviorgpt": verdicts(default_results),
        "workflow_without_behaviorgpt": verdicts(off),
        "verdicts_identical": verdicts(default_results) == verdicts(off),
        "behaviorgpt_as_ranker": verdicts(replay(run, "behaviorgpt")),
        "blend_as_ranker": verdicts(replay(run, "blend")),
    }

    ms = sorted(c["ms"] for c in CALLS)
    report["api_calls"] = {
        "total": len(CALLS),
        "in_part_1": n_after_1,
        "latency_ms_p50": ms[len(ms) // 2],
        "latency_ms_p95": ms[int(len(ms) * 0.95)],
        "items_per_call": sorted({c["items"] for c in CALLS}),
    }
    out = ROOT / "results" / "behaviorgpt_audit.json"
    out.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "steps"}, indent=2, default=str))


if __name__ == "__main__":
    main()
