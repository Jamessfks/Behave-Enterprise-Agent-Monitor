# 0001. Merge sales-env into one codebase and one app

- **Status:** Accepted, 2026-11-08
- **Deciders:** project owner, with the sales-env author's branch as input

## Context

Two builds grew in parallel from `16692d2`:
- **`main`:** Agent Monitor. A stateless FastAPI app with three checks per agent step, a canvas
  UI, and a small NovaDesk/Acme Industries world.
- **`sales-env`:** a separate FastAPI app with a rich fake workspace (Jmail, Jdrive, Habspot,
  Calendario, quotes), a ShiftPoint world, its own event log, catalog and monitor stub.

`git merge` has no textual conflicts (sales-env only adds files under `sales-env/`). The
conflicts are in the design: two apps, two worlds, two event formats, two catalogs, two monitors.

## Decision

- Merge with history (`git merge --no-ff origin/sales-env`) on `merge/sales-env` and land it
  through a pull request. The teammate's commits keep their authorship.
- Restructure into **one** package layout and **one** FastAPI app (`server.py`):
  - `workspace/`: the sales-env app (routers, templates, static, store, events, catalog)
  - `world/`: the ShiftPoint data, plus `world/seed/state.json`
  - `monitor/`: the three checks
  - `agent/`: the live Claude agent
  - `scenarios/`: scripted runs
  - `web/`: the monitor UI
- Files are moved with `git mv` so `git log --follow` keeps their history.

## Consequences

- One process, one deploy, one test suite, one dependency file (`pyproject.toml`).
- sales-env's README run instructions (`cd sales-env && uvicorn app.main:app`) change to the
  root README's.
- Later ADRs record each part that was replaced: the monitor stub (0005), the event format
  (0006), the catalog (0007), rules (0008), playback (0009).

## Alternatives considered

- **Keep two apps connected over HTTP** (sales-env `MONITOR_MODE=remote` → main `/api/check`).
  Less churn, but two deploys, a network hop in every write, and two state models. Rejected:
  the owner asked for one MVP and allowed restructuring.
