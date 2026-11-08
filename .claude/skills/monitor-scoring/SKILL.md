---
name: monitor-scoring
description: Implement, change, calibrate or debug Sentinel's monitor — per-step probability from BehaviorGPT rankings, excess surprisal, CUSUM risk score, threshold calibration on clean runs, and alert explanations. Use when touching monitor/ code, setting the threshold, or when an alert fires (or fails to) unexpectedly.
---

# Monitor scoring

The method is Unbox's published anomaly detector, adapted. Read
`docs/reference/anomaly-method.md` first. When in doubt, read the upstream code it cites
(`anomaly/scoring.py`, `anomaly/detector.py` in Unbox-AI/behaviorgpt-anomaly, MIT). Copy and
attribute it rather than re-deriving it.

## Pipeline per event (keep this shape)

```
event ─► plan(): context | scored | funnel
scored ─► ranker.rank(history) → {action_id: score} for the whole catalog
       ─► p = softmax(score/τ) mixed with ε=0.02 uniform; surprisal, entropy
       ─► u = clip((surprisal − entropy − loc) / scale, −3, 6)
       ─► S = max(0, S + u − k), k = 0.5;  risk = S / barrier
risk ≥ 1 ─► flagged: pause agent, emit alert with top-u steps + expected actions + reasons
```

- `ranker` is an interface with two implementations: `BehaviorGPTRanker` (one `complete` call with
  `limit=len(catalog)`, so the softmax is exact for a small catalog) and `TransitionRanker` (the
  no-go fallback). Nothing downstream may know which one is in use.
- Scored = the first touch of an `action_id` in the run. Repeats are `funnel`, searches are
  `context`. Events with `details.irreversible` are scored like any other, and the environment also
  calls `/gate` before executing them, so they're held when risk is already high.
- Monitor output must match "Monitor output per step" in `docs/event-schema.md`.

## Calibration (`monitor/calibrate.py` → `monitor/calibration.json`)

From the clean runs in `runs/` (never the mistake run):
1. τ: grid search (geomspace 0.002–0.5) maximizing Σ log p over scored steps. Fit it separately
   for steps right after a search vs not, if there's enough data. Otherwise use one τ.
2. loc/scale: median and 1.4826·MAD of excess surprisal over scored steps (scale floor 1e-3).
3. barrier: the max CUSUM of each clean run, taken at a high quantile (with only 3–5 clean runs, use
   max × 1.25).
4. Check: every clean run stays < 100% risk, and the mistake run crosses 100% **at or just after**
   the injected step. Record both in `calibration.json` with the run ids used.

Few runs make this fragile. Say so in the pitch, and don't tune the barrier just to make the demo
fire.

## Explanations (what the alert card shows)

For the 1–3 steps with the largest positive u: the action name, p and rank, the top-3 expected
actions with p, and rule reasons from simple checks, such as:
- an irreversible action (send/delete) before any lookup action in the run
- an action on an entity that differs from the entity in the triggering email (from
  `details.entity`; this covers the "right steps, wrong client" blind spot)
- a destructive action (`*.delete_*`)

## Debugging an alert

- Fired on a clean run: print the per-step table (action, rank, p, entropy, u, S). Usually one
  step has rank ≫ 5. Either its catalog `name` is unclear, or that step is a repeat that should
  be `funnel`.
- Didn't fire on the mistake run: check whether the wrong action is in the catalog at all (unknown
  ids can't be scored) and its rank at that step.
- Cache rankings on disk; never re-hit the API for a prefix you've already scored.
