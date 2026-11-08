# Scoring method — adapted from Unbox's anomaly detector

Unbox already published the method our brief describes:
[Unbox-AI/behaviorgpt-anomaly](https://github.com/Unbox-AI/behaviorgpt-anomaly) (MIT). It scores
each step of a shopping session, accumulates risk, and flags the step where the session crosses a
calibrated barrier. The key files are `anomaly/scoring.py`, `anomaly/detector.py` and
`scripts/calibrate.py`. **Reuse its code rather than reinventing it**, and keep the MIT notice on
anything copied.

## 1. A probability per step

The API returns ranking **scores**, not probabilities. For each scored step, make two calls on
the history so far:

- **head:** `complete(history, limit=100)` gives the top 100 items with scores.
- **tail:** `complete(history, limit=100, filters={"id": [actual] + 99 sampled ids})` gives the
  score of the action actually taken, plus a uniform reference sample.

Softmax with temperature τ, with the partition function = exact head sum + estimated tail sum:

```
p(a | history) = exp(s_a/τ) / [ Σ_head exp(s/τ) + (N − |head|) · mean_sample exp(s/τ) ]
```

A uniform mixture ε = 2% caps the surprisal of any one step. τ is fitted by maximum likelihood on
normal runs, separately for "after a search" and "browsing".

**Sentinel simplification:** our catalog is small (~30–60 actions), so `limit=N` returns the
whole catalog in one call. Then no tail sampling is needed and the softmax is exact.

## 2. Normalize for context

- surprisal = −log p
- **excess surprisal** = surprisal − entropy of the model's prediction. It averages 0 for a normal
  actor in any context: a broad context makes everything less likely, a narrow one doesn't.
- u = (excess − median_normal) / MAD-scale_normal, clipped to [−3, 6].

## 3. What counts as a scored choice

- `Search` sets context and isn't scored.
- **The first touch of an item is scored.** Later events on an already-touched item are "funnel"
  steps and aren't scored, because the model ranks seen items low on purpose.
- Orders aren't scored. They are where you hold for review if risk is high.

**Implication for the action catalog:** make actions specific and semantic (action × object) so
that a correct run touches each catalog item about once. Generic UI verbs ("click", "type")
repeat constantly and carry no meaning.

## 4. Risk barrier (CUSUM)

```
S_t = max(0, S_{t−1} + u_t − k),   k = 0.5
risk_t = S_t / barrier
```

Evidence builds while behavior stays off and drains while it's normal, so a run that goes wrong
halfway is caught at the turn. The **barrier** is the CUSUM level that only ~2% of normal runs ever
reach (calibrated on known-good runs). risk ≥ 100% → flag → pause the agent.

## 5. Explanations

For the steps with the largest u, report the probability and rank, the top-3 actions the model
expected instead, and simple rule-based reasons (e.g. "sent an email before looking up the
company"). This is what the alert card shows.

## Known blind spot (keep it in the pitch)

Upstream reports a 0% catch rate for "takeover via search", where every step is individually
normal. A behavioral monitor can't tell a wrong-but-plausible intent from a right one. For Sentinel,
the equivalent case is an agent that does the right steps for the **wrong client**. That needs a
content check (entity consistency), not just the sequence.

## Go/no-go test (first hour)

1. Embed the action catalog.
2. For a hand-written correct run, call `complete` on each prefix and record the true next
   action's rank.
3. **Go** if the true action is usually in the top ~5 of the catalog. **No-go** → fall back to a
   first-order transition model (counts of a→b from the scripted runs, add-one smoothed). Feed it
   into the same u / CUSUM pipeline so nothing downstream changes.
