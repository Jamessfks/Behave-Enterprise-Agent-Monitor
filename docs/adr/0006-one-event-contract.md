# 0006. One event contract: the workspace event, adapted for the checks

- **Status:** Accepted, 2026-11-08

## Context

Two formats existed:
- **main's step event:** `{run_id, step, timestamp, type, action_id, query, details{...}}`
  (`docs/event-schema.md`, old version).
- **The workspace event:** `{id, ts, run_id, run, app, action, object, args, ctx, catalog_action,
  irreversible, before, decision, ...}` (`docs/event-contract.md`).

## Decision

- **The workspace event is the one stored and shown format** (`docs/event-contract.md`). Run logs,
  approved runs (`runs/approved/*.jsonl`) and the `/events` page all use it. Two fields were added:
  `by` (`agent` | `human`) and `approval_id` (on an approved replay).
- **`monitor/adapter.py`** converts workspace events into the checks' step events at check time:
  - drop `ui`, `session`, `sentinel`, side events, human actions, and paused or blocked writes
    that never happened;
  - `type` is `search` or `view`; `action_id` is `catalog_action`;
  - `entity` is the company the object belongs to;
  - `values` are normalized typed values (amount, close_date, locations, discount_pct…);
  - `source` is the opened object id.

  It's applied when loading stored runs too, so re-tagging never needs re-recording.
- **The monitor's verdict is stored on the event** as `monitor` (checks, failed, headline,
  reasons). The canvas reads step views built from it (`scenarios/runner.py`, contract in
  `docs/event-schema.md`).

## Consequences

- One format to log, replay and debug. The old main event schema exists only inside the adapter.
- Changing a workspace field means updating the adapter and its tests, not every consumer.
