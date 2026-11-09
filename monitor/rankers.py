"""Rankers: given a history of step events, score every action in the catalog.

- WorkflowRanker (decides): the company's own workflow dependencies, learned from approved runs.
- BehaviorGPTRanker (evidence only, ADR 0004): BehaviorGPT's zero-shot ranking. `complete()`
  returns at most 100 results, so the catalog is ranked in chunks of ids and merged. Every
  response is cached in `runs/rankings_cache.json`, so replays need no API key.
- TransitionRanker: first-order transition counts, kept for comparison.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Protocol

from monitor.catalog import id_chunks, load_catalog
from monitor.events import to_sdk

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = ROOT / "runs" / "rankings_cache.json"


class Ranker(Protocol):
    name: str

    def rank(self, history: list[dict[str, Any]]) -> dict[str, float]:
        """Score of every catalog action as the next step after `history` (higher = likelier)."""
        ...


def history_key(catalog_id: str, history: list[dict[str, Any]]) -> str:
    parts = [f"s:{e['query']}" if e["type"] == "search" else f"v:{e['action_id']}" for e in history]
    return catalog_id + "|" + "|".join(parts)


class RankingCache:
    def __init__(self, path: Path = CACHE_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, float]] = (
            json.loads(path.read_text()) if path.exists() else {}
        )

    def get(self, key: str) -> dict[str, float] | None:
        return self._data.get(key)

    def put(self, key: str, scores: dict[str, float]) -> None:
        with self._lock:
            self._data[key] = scores
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self._data, sort_keys=True, separators=(",", ":")))
                tmp.replace(self.path)
            except OSError:  # read-only file system (e.g. Vercel): keep it in memory
                pass

    def __len__(self) -> int:
        return len(self._data)


def default_examples(k: int | None = None) -> list[list[dict[str, Any]]]:
    """The warm start used in Live mode (ADR 0013): the first k approved runs (runs/approved/),
    BGPT_WARM_START=k (default 3). On approved runs outside the examples, 3 example runs moved
    the true next step from median rank 86 of 139 to 1."""
    from monitor.core import approved_runs  # local import: core imports this module

    k = int(os.environ.get("BGPT_WARM_START", "3")) if k is None else k
    return approved_runs()[:k] if k > 0 else []


class BehaviorGPTRanker:
    """BehaviorGPT ranks the next step. Cold by default (the demo task). With `examples` (Live
    mode, ADR 0013), approved runs go first as earlier sessions (the SDK takes a list of
    sessions), so the model sees how this company does the work before it scores the run in
    progress. A run is never among its own examples."""

    name = "behaviorgpt"

    def __init__(
        self,
        catalog_id: str | None = None,
        client: Any = None,
        cache: RankingCache | None = None,
        examples: list[list[dict[str, Any]]] | None = None,
        pick: Any = None,
    ):
        self.catalog_id = catalog_id or os.environ.get("UNBOXAI_CATALOG_ID", "")
        self.cache = cache if cache is not None else RankingCache()
        self._client = client
        self.examples = examples or []
        self.pick = pick  # history -> example runs (Live: runs about the same account)
        self.n_actions = len(load_catalog())
        self.calls = 0
        self.cache_hits = 0

    def _for(self, history: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Example runs for this history: swap out the run being scored (replays, calibration)."""
        rid = history[0].get("run_id") if history else None
        ex = self.pick(history) if self.pick else self.examples
        if rid and any(r and r[0].get("run_id") == rid for r in ex):
            pool = default_examples(1000)
            ex = [r for r in pool if r and r[0].get("run_id") != rid][: len(ex)]
        return ex

    def _key(self, history: list[dict[str, Any]], ex: list[list[dict[str, Any]]]) -> str:
        key = history_key(self.catalog_id, history)
        if not ex:
            return key  # cold start: the same keys as the committed cache
        warm = ",".join(str(r[0].get("run_id")) for r in ex if r)
        return key.replace("|", f"|warm:{warm}|", 1)

    @property
    def client(self):
        if self._client is None:
            from monitor.unbox import get_client

            self._client = get_client()
        return self._client

    @property
    def available(self) -> bool:
        return bool(self.catalog_id) and (
            bool(os.environ.get("UNBOXAI_API_KEY")) or self._client is not None
        )

    def cached(self, history: list[dict[str, Any]]) -> bool:
        return self.cache.get(self._key(history, self._for(history))) is not None

    def _complete_with_retry(self, sdk_history, chunk: list[str]):
        return _with_retry(
            lambda: self.client.complete(
                sdk_history,
                limit=len(chunk),
                catalog_id=self.catalog_id,
                filters={"id": chunk},
                register_event=False,
            )
        )

    def rank(self, history: list[dict[str, Any]]) -> dict[str, float]:
        """Scores of the whole catalog. `complete()` returns at most 100 results, so a larger
        catalog is ranked in chunks of ids (same history, same model call), then merged."""
        ex = self._for(history)
        key = self._key(history, ex)
        hit = self.cache.get(key)
        if hit is not None:
            self.cache_hits += 1
            return hit
        current = [to_sdk(e) for e in history]
        sessions = [[to_sdk(e) for e in r] for r in ex if r] + ([current] if current else [])
        sdk_history = sessions if len(sessions) > 1 else (sessions[0] if sessions else [])
        scores: dict[str, float] = {}
        for chunk in id_chunks():
            res = self._complete_with_retry(sdk_history, chunk)
            self.calls += 1
            scores.update({item.id: float(item.score) for item in res.items})
        self.cache.put(key, scores)
        return scores


class WorkflowRanker:
    """The company's own workflow habits, learned from approved runs (the no-go fallback).

    Order varies between good runs; dependencies don't. For each action a, frac(b, a) is the
    share of normal runs containing a in which b happened before a. The cost of doing a next is
    the sum of frac(b, a) over the usual predecessors b not done yet; actions never seen in a
    normal run cost `unseen`. Score = -cost (higher = likelier). Repeats are ranked low, like
    BehaviorGPT does.
    """

    name = "workflow"

    def __init__(
        self,
        runs: list[list[dict[str, Any]]],
        unseen: float = 8.0,
        actions: list[str] | None = None,
    ):
        self.actions = list(actions) if actions is not None else list(load_catalog())
        self.unseen = unseen
        before: dict[str, Counter] = defaultdict(Counter)
        adjacent: dict[str, Counter] = defaultdict(Counter)
        count: Counter = Counter()
        for run in runs:
            done: list[str] = []
            for e in run:
                if e["type"] != "view" or e["action_id"] in done:
                    continue
                count[e["action_id"]] += 1
                for b in set(done):
                    before[e["action_id"]][b] += 1
                if done:
                    adjacent[e["action_id"]][done[-1]] += 1
                done.append(e["action_id"])
        self.frac = {
            a: {b: n / count[a] for b, n in before[a].items() if n / count[a] >= 0.5} for a in count
        }
        # Hard dependencies: b comes right before a in >= 90% of runs (ask -> read the reply).
        # A skipped hard dependency is never excused: a reply can't be read before asking.
        self.hard = {a: {b for b, n in adjacent[a].items() if n / count[a] >= 0.9} for a in count}

    def missing(self, history: list[dict[str, Any]], action: str) -> list[tuple[str, float]]:
        """Usual predecessors of `action` that haven't happened yet, most usual first."""
        done = {e["action_id"] for e in history if e["type"] == "view"}
        pre = self.frac.get(action, {})
        return sorted(((b, f) for b, f in pre.items() if b not in done), key=lambda x: -x[1])

    def excused(self, history: list[dict[str, Any]]) -> set[str]:
        """Predecessors already skipped by an earlier step: a skip is charged once, where it
        happened, not again on every later step."""
        done: set[str] = set()
        out: set[str] = set()
        for e in history:
            if e["type"] != "view":
                continue
            out |= {b for b in self.frac.get(e["action_id"], {}) if b not in done}
            done.add(e["action_id"])
        return out - done

    def rank(self, history: list[dict[str, Any]]) -> dict[str, float]:
        done = {e["action_id"] for e in history if e["type"] == "view"}
        skip = done | self.excused(history)
        out = {}
        for a in self.actions:
            if a not in self.frac:
                cost = self.unseen
            else:
                hard = self.hard.get(a, set())
                cost = sum(
                    f for b, f in self.frac[a].items() if b not in (done if b in hard else skip)
                )
            if a in done:
                cost += self.unseen / 2
            out[a] = -cost
        return out


RETRY_DELAYS = (0.5, 1.5)  # seconds; then give up and let the caller handle the error


def _retryable(err: Exception) -> bool:
    from behaviorgpt import RateLimitError, UnboxAIError

    if isinstance(err, RateLimitError):
        return True
    return isinstance(err, UnboxAIError) and (err.status_code or 0) >= 500


def _with_retry(call, sleep=time.sleep):
    """Retry rate limits (429) and server errors (5xx), as Unbox's own anomaly app does."""
    for delay in (*RETRY_DELAYS, None):
        try:
            return call()
        except Exception as e:
            if delay is None or not _retryable(e):
                raise
            sleep(delay)
    return None  # unreachable


class TransitionRanker:
    """P(next | previous action) interpolated with P(next), add-k smoothed, as log-probs."""

    name = "transition"

    def __init__(self, runs: list[list[dict[str, Any]]], k: float = 0.1, lam: float = 0.7):
        self.actions = list(load_catalog())
        self.k, self.lam = k, lam
        self.bigram: dict[str, Counter] = defaultdict(Counter)
        self.unigram: Counter = Counter()
        for run in runs:
            prev = "<start>"
            for e in run:
                if e["type"] != "view":
                    continue
                self.bigram[prev][e["action_id"]] += 1
                self.unigram[e["action_id"]] += 1
                prev = e["action_id"]

    def _p(self, counts: Counter, a: str) -> float:
        total = sum(counts.values())
        return (counts[a] + self.k) / (total + self.k * len(self.actions))

    def rank(self, history: list[dict[str, Any]]) -> dict[str, float]:
        views = [e["action_id"] for e in history if e["type"] == "view"]
        prev = views[-1] if views else "<start>"
        seen = set(views)
        out = {}
        for a in self.actions:
            p = self.lam * self._p(self.bigram[prev], a) + (1 - self.lam) * self._p(self.unigram, a)
            if a in seen:  # like BehaviorGPT: repeats are ranked low on purpose
                p *= 0.05
            out[a] = math.log(p)
        return out
