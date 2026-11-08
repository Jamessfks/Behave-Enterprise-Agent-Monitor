---
name: go-no-go
description: Run Sentinel's go/no-go transfer test — does BehaviorGPT, pretrained on consumer behavior, rank the correct next office-workflow action highly? Use in the first hour after the catalog is embedded, after any big catalog rewrite, or when someone asks whether the model "works" on our workflow.
---

# Go/no-go transfer test

Question: given a correct run's prefix, where does BehaviorGPT rank the action that actually came
next? This decides whether the monitor uses BehaviorGPT or the fallback transition model.

## Inputs

- An embedded catalog (`UNBOXAI_CATALOG_ID` in `.env`; see the `action-catalog` skill).
- One or more correct runs in `runs/*.jsonl`, in the format from `docs/event-schema.md`. If none
  are recorded yet, hand-write the correct workflow from `docs/PROJECT.md` Phase 0 as a run file.

## Procedure

1. For each run, for each step i with `type == "view"` whose `action_id` hasn't appeared earlier:
   - history = events[:i] converted to SDK events (`search` → `Search(query)`, `view` →
     `View(action_id)`; use `monitor.events.to_sdk`)
   - `res = client.complete(history, limit=<catalog size>, register_event=False)`
   - record the rank (1-based) of `action_id` in `res.items`, and the top 3 names
2. Also run the **mistake run**: its wrong step should rank low.
3. Cache every response on disk (key: catalog id + JSON of the history). Re-runs must be free.

Write the script to `monitor/go_no_go.py`. Print a table: step, true action, rank, top-3 predicted.
Save results to `results/go_no_go.json` for the demo slide.

## Verdict

- **Go:** median rank of true actions ≤ 5 *and* the mistake step ranks clearly worse than the
  correct steps around it.
- **No-go:** otherwise. Before giving up, try once: rewrite weak `name`s to be more descriptive,
  and check whether starting the history with a `Search` describing the task ("reply to inbound
  sales lead with a quote") helps. Re-embed and rerun.
- Still no-go → build the fallback (first-order transition counts from the scripted runs,
  add-one smoothing) behind the same interface. See the `monitor-scoring` skill.

Report honestly either way. The result goes on a pitch slide ("does it transfer to office work?"),
so numbers must come from the run, never estimated.
