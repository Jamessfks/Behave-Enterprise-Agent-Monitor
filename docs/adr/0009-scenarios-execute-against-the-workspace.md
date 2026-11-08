# 0009. Demo runs execute against the real workspace, step by step

- **Status:** Accepted, 2026-11-08

## Context

main's demo replayed recorded events through a stateless `/api/check`, so nothing actually
changed anywhere. The owner wants Jmail, Jdrive, Habspot, Calendario and quotes to show the
agent's changes after a run.

## Decision

- **Scenarios are data:** `world/scenarios/<id>.json` holds the `common` steps, then `careful`
  or `mistakes` steps. Each step is one HTTP call the agent makes (method, path, body or query,
  the page to show, an optional `save_as`). Later steps reference earlier responses as
  `${name.field}`, e.g. the id of a created quote.
- **`scenarios/runner.py`** runs one step per `POST /api/runs/current/next` through
  `workspace/dispatch.py` as the agent. It returns the step view the canvas needs: label, app,
  page, decision, approval id and the monitor's checks, plus "what changed" links.
- **Progress lives in `RUN_STATE["scenario"]`**, so it's part of the snapshot (ADR 0003).
- **On a pause**, the runner waits. After Allow or Block it records what an approval created and
  continues. A step that depends on something that never happened is skipped and says so.
- **Training data:** `scripts/make_runs.py` runs the teammate's scripted agents
  (`scenarios/http_runner.py`) in-process with the monitor off. They go to `runs/approved/`
  (21 runs) and `runs/eval/` (the mistakes run, never trained on).

## Consequences

- After a run, the apps really changed: the deal's stage and note, offer docs, sent mail and
  drafts, the calendar event. Blocked steps change nothing.
- Adding a scenario is a JSON file, not code.
- Runs aren't byte-identical across executions (new ids, wall-clock timestamps). Tests assert
  behavior, not ids.
