"""Check 1, "Is this step normal?": per-step surprise from a ranker, accumulated with CUSUM.

Method from Unbox AI's behaviorgpt-anomaly (`anomaly/detector.py`), MIT License, adapted:
excess surprisal (surprisal minus the prediction's entropy), standardized on normal runs and
clipped; a one-sided CUSUM; a barrier calibrated on known-good runs. See
docs/reference/anomaly-method.md.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from behaviorgpt import UnboxAIError

from monitor.rankers import BehaviorGPTRanker, WorkflowRanker
from monitor.scoring import predict

log = logging.getLogger(__name__)

CLIP = (-3.0, 6.0)
K = 0.5
EPS = 0.02
# Irreversible steps (send, delete, share) can't be undone, so they get a stricter, per-step
# gate on top of the CUSUM: u >= 3 means "about 20x less likely than usual".
IRREVERSIBLE_U = 3.0


class BlendRanker:
    """BehaviorGPT's zero-shot ranking plus the company's own step-to-step habits.

    score = transition log-prob + beta * (standardized BehaviorGPT score). BehaviorGPT can't be
    fine-tuned, so this is how one company's approved runs adapt it. beta is fitted on held-out
    normal runs (monitor/calibrate.py); beta = 0 means BehaviorGPT adds nothing.
    """

    name = "blend"

    def __init__(self, bgpt: BehaviorGPTRanker, transition: WorkflowRanker, beta: float):
        self.bgpt, self.transition, self.beta = bgpt, transition, beta

    def rank(self, history: list[dict[str, Any]]) -> dict[str, float]:
        t = self.transition.rank(history)
        b = self.bgpt.rank(history)
        vals = np.asarray(list(b.values()), dtype=float)
        mu, sd = float(vals.mean()), float(vals.std()) or 1.0
        lo = float(vals.min())
        return {a: t[a] + self.beta * ((b.get(a, lo) - mu) / sd) for a in t}


@dataclass
class NormalVerdict:
    status: str  # scored | context | funnel | unknown
    ok: bool = True
    p: float | None = None
    rank: int | None = None
    u: float | None = None
    cusum: float = 0.0
    risk: float = 0.0
    expected: list[tuple[str, float]] = field(default_factory=list)
    bgpt_rank: int | None = None
    bgpt_top: list[str] = field(default_factory=list)


class NormalCheck:
    def __init__(self, ranker, cal: dict[str, float], bgpt: BehaviorGPTRanker | None = None):
        self.ranker = ranker
        self.tau, self.loc, self.scale = cal["tau"], cal["loc"], cal["scale"]
        self.barrier = cal["barrier"]
        self.bgpt = bgpt  # shown for transparency, whatever ranker decides

    def evaluate(
        self, history: list[dict[str, Any]], event: dict[str, Any], cusum: float
    ) -> NormalVerdict:
        if event["type"] == "search":
            return NormalVerdict("context", cusum=cusum, risk=cusum / self.barrier)
        seen = {e["action_id"] for e in history if e["type"] == "view"}
        if event["action_id"] in seen:
            return NormalVerdict("funnel", cusum=cusum, risk=cusum / self.barrier)
        scores = self.ranker.rank(history)
        if event["action_id"] not in scores:
            return NormalVerdict("unknown", cusum=cusum, risk=cusum / self.barrier)
        pred = predict(scores, event["action_id"], self.tau, EPS)
        u = (pred.surprisal - pred.entropy - self.loc) / self.scale
        u = min(max(u, CLIP[0]), CLIP[1])
        s = max(0.0, cusum + u - K)
        irreversible = bool((event.get("details") or {}).get("irreversible"))
        v = NormalVerdict(
            "scored",
            ok=s < self.barrier and not (irreversible and u >= IRREVERSIBLE_U),
            p=float(np.exp(pred.logp)),
            rank=pred.rank,
            u=u,
            cusum=s,
            risk=s / self.barrier,
            expected=pred.top,
        )
        if self.bgpt is not None and (self.bgpt.available or self.bgpt.cached(history)):
            try:
                b = self.bgpt.rank(history)
                order = sorted(b, key=b.get, reverse=True)
                v.bgpt_rank = (
                    order.index(event["action_id"]) + 1 if event["action_id"] in b else None
                )
                v.bgpt_top = order[:3]
            except (UnboxAIError, OSError) as e:  # advisory here: never block on an outage
                log.warning("BehaviorGPT unavailable for this step: %s", e)
        return v


def scored_observations(ranker, runs: list[list[dict[str, Any]]]):
    """(scores, target) for every first-touch view in `runs`."""
    out = []
    for run in runs:
        seen = set()
        for i, e in enumerate(run):
            if e["type"] != "view" or e["action_id"] in seen:
                continue
            out.append((ranker.rank(run[:i]), e["action_id"]))
            seen.add(e["action_id"])
    return out


def run_cusum(check: NormalCheck, run: list[dict[str, Any]], reset_on_flag: bool = True):
    """Per-step verdicts for a whole run; after a flag the CUSUM resets (as Allow/Block does)."""
    cusum, out = 0.0, []
    for i, e in enumerate(run):
        v = check.evaluate(run[:i], e, cusum)
        cusum = v.cusum
        if not v.ok and reset_on_flag:
            cusum = 0.0
        out.append(v)
    return out


def group_by_prefix(runs):
    groups = defaultdict(list)
    for r in runs:
        groups[r[0]["run_id"].split("_")[0]].append(r)
    return groups
