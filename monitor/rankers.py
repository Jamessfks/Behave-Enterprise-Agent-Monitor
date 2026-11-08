"""Rankers: given a history of events, score every action in the catalog.

Two implementations behind one interface, so nothing downstream knows which one runs:

- BehaviorGPTRanker: one `complete()` call ranks the whole catalog (it holds <= 100 actions).
  Every response is cached in `runs/rankings_cache.json`, which is committed, so replay mode
  gives the same BehaviorGPT scores with no API key.
- TransitionRanker: the no-go fallback. Interpolated first-order transition counts fitted on
  normal runs, as log-probabilities.
"""

from __future__ import annotations

import json
import math
import os
import threading
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Protocol

from monitor.catalog import load_catalog
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


class BehaviorGPTRanker:
    name = "behaviorgpt"

    def __init__(
        self,
        catalog_id: str | None = None,
        client: Any = None,
        cache: RankingCache | None = None,
    ):
        self.catalog_id = catalog_id or os.environ.get("UNBOXAI_CATALOG_ID", "")
        self.cache = cache if cache is not None else RankingCache()
        self._client = client
        self.n_actions = len(load_catalog())
        self.calls = 0
        self.cache_hits = 0

    @property
    def client(self):
        if self._client is None:
            from behaviorgpt import UnboxAIClient

            self._client = UnboxAIClient(market="us")
        return self._client

    @property
    def available(self) -> bool:
        return bool(self.catalog_id) and (
            bool(os.environ.get("UNBOXAI_API_KEY")) or self._client is not None
        )

    def cached(self, history: list[dict[str, Any]]) -> bool:
        return self.cache.get(history_key(self.catalog_id, history)) is not None

    def rank(self, history: list[dict[str, Any]]) -> dict[str, float]:
        key = history_key(self.catalog_id, history)
        hit = self.cache.get(key)
        if hit is not None:
            self.cache_hits += 1
            return hit
        res = self.client.complete(
            [to_sdk(e) for e in history],
            limit=self.n_actions,
            catalog_id=self.catalog_id,
            register_event=False,
        )
        self.calls += 1
        scores = {item.id: float(item.score) for item in res.items}
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

    def __init__(self, runs: list[list[dict[str, Any]]], unseen: float = 8.0):
        self.actions = list(load_catalog())
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
