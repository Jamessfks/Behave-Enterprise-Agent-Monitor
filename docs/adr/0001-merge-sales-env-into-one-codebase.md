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
- **One repository, one deploy, two FastAPI apps** (the owner's call, 2026-11-08: "a separate
  FastAPI app with its own world"):
  - **The workspace** (`workspace/main.py`, `create_app()`): its own FastAPI app (Jmail, Jdrive,
    Habspot, Calendario, quotes, approvals, event log) over its own world (`world/`). It runs
    alone with `uvicorn workspace.main:app`.
  - **The monitor server** (`server.py`): the run APIs, the Unbox catalog tools, and the canvas
    at `/monitor/`. It mounts the workspace app at `/`, so one Vercel deploy serves both.
- Files moved with `git mv`, so `git log --follow` keeps their history:
  `sales-env/app` → `workspace/`, `sales-env/world` → `world/`, seed → `world/seed/`, scripts →
  `scripts/world/` and `scenarios/http_runner.py`.

## Consequences

- One process, one deploy, one state store, one test suite, one dependency file (`pyproject.toml`).
- The monitor checks every step in-process (ADR 0005), with no network hop, even though the
  workspace is its own app.
- sales-env's README run instructions (`cd sales-env && uvicorn app.main:app`) change to the
  root README's.
- Later ADRs record each part that was replaced: the monitor stub (0005), the event format
  (0006), the catalog (0007), rules (0008), playback (0009).

## Alternatives considered

- **Two apps, two deploys, connected over HTTP** (sales-env's original `MONITOR_MODE=remote`).
  Rejected by the owner: two deploys, a network hop on every write, and shared state to wire up.
- **One app with the workspace routers folded in.** Simpler routing, but the owner wants the
  workspace to stay its own app with its own world.
