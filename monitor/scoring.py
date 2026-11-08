"""Probability, entropy and rank of the action taken, from ranking scores.

Adapted from Unbox AI's behaviorgpt-anomaly (`anomaly/scoring.py`),
https://github.com/Unbox-AI/behaviorgpt-anomaly, MIT License, Copyright (c) 2026 Unbox AI.

Change from upstream: our catalog is small (<= 100 actions), so one ranking call returns every
action's score and the softmax is exact; upstream estimates the tail of a large catalog from a
uniform sample.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Prediction:
    logp: float
    surprisal: float
    entropy: float
    rank: int  # 1 = the model's top pick
    top: list[tuple[str, float]]  # (action_id, p), best first


def _logsumexp(x: np.ndarray) -> float:
    m = float(np.max(x))
    return m + math.log(float(np.sum(np.exp(x - m))))


def predict(scores: dict[str, float], target: str, tau: float, eps: float) -> Prediction:
    """p(target | history) from a softmax over every action's score, mixed with eps uniform."""
    ids = list(scores)
    s = np.asarray([scores[i] for i in ids], dtype=float) / tau
    p = np.exp(s - _logsumexp(s))
    p = (1 - eps) * p + eps / len(ids)
    by_id = dict(zip(ids, p, strict=True))
    p_target = float(by_id.get(target, eps / len(ids)))
    order = np.argsort(-p)
    rank = (
        int(np.where(np.asarray(ids)[order] == target)[0][0]) + 1 if target in by_id else len(ids)
    )
    return Prediction(
        logp=math.log(p_target),
        surprisal=-math.log(p_target),
        entropy=-float(np.sum(p * np.log(p))),
        rank=rank,
        top=[(ids[i], float(p[i])) for i in order[:3]],
    )


def fit_tau(obs: list[tuple[dict[str, float], str]], eps: float) -> float:
    """The temperature that makes the observed choices most likely (maximum likelihood)."""
    grid = np.geomspace(0.002, 20.0, 160)
    if not obs:
        return 1.0
    ll = [sum(predict(sc, t, float(tau), eps).logp for sc, t in obs) for tau in grid]
    return float(grid[int(np.argmax(ll))])


def robust_location_scale(values: list[float], min_scale: float = 1.0) -> tuple[float, float]:
    """Median and MAD-based standard deviation, so outliers don't move the barrier.

    Change from upstream (floor 1e-3): a company's approved runs are few and nearly
    deterministic, so the MAD can be tiny and any mild deviation would saturate. The scale is
    floored at `min_scale` nats: one unit of u means "e times less likely than usual".
    """
    x = np.asarray(values, dtype=float)
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med))) * 1.4826
    return med, max(mad, min_scale)
