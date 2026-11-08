# 0005. The monitor runs in-process at the workspace's single write gate

- **Status:** Accepted, 2026-11-08

## Context

sales-env already routes every write through `events.commit()`. That calls `monitor.check()`
and acts on `allow | flag | pause | block`. Its monitor was a stub: off, a few rules, or a
blocking HTTP call to a remote URL.

## Decision

- **`workspace/monitor.py`** calls `monitor.workspace_gate.check(event, history, run,
  run_state, data, learned, gate=...)` in the same process. `MONITOR_MODE=agent` is the default
  and `off` records training runs. The remote and shadow modes are gone.
- **Writes are gated.** Allow applies the write; pause stores the request and returns 202 plus an
  approval id; block returns 403 for hard rules. **The agent's reads are scored, never gated**: a
  failed check shows as a flag.
- **Actors.** Requests with `X-Actor: agent` (the scenario runner and the live agent, through
  `workspace/dispatch.py`) are logged and gated. Requests from a person browsing the apps (the
  iframe, a tab) aren't gated, and their reads aren't logged, so looking at the apps never
  changes the run.
- **Approval replays the original request.** `events.approve()` replays the recorded
  method, path and body through the same route with an `APPROVED` context. The first matching
  commit skips the monitor and is logged with `approval_id`. The reason becomes a learned rule.
- **`workspace/dispatch.py`** calls the workspace's own routes in-process (route matching plus
  `route.handle`), so the runner, the live agent and replays reuse the HTTP routes exactly.

## Consequences

- One code path for every actor. A scripted step, a live tool call and a person's click change
  state the same way.
- No network hop and no fail-open/fail-closed question: if the monitor raises, the request fails.
- `APPROVE_EXTERNAL_SENDS=1` still makes every external send wait for a person.
