# Agent Monitor (sudai2)

Hackathon MVP: an AI sales agent works in a fake workspace (Jmail, Jdrive, Habspot CRM,
Calendario, quotes) for the fictional company ShiftPoint, and every step it takes is checked
before it counts: a step model learned from approved runs, a fact check and a rules check. A
person allows (with a reason, which becomes a rule) or blocks paused steps. BehaviorGPT ranks
every step live but is **evidence only**: it never changes a verdict (ADR 0004, enforced by a
test).

## Architecture (read docs/adr/ first; the index is docs/adr/README.md)

- **Two FastAPI apps, one deploy** (ADR 0001):
  - `workspace/` is its own app (`workspace.main.create_app()`) over its own world (`world/`);
  - `server.py` mounts it at `/` and serves the monitor canvas (`web/`) at `/monitor/` plus the
    run APIs.
- **One write gate.** `workspace/events.py commit()` → `workspace/monitor.py` →
  `monitor/workspace_gate.check()`, in-process (ADR 0005). Only `X-Actor: agent` requests are
  logged and gated.
- **State.** `workspace/state.py`: MemoryStore locally, Upstash Redis on Vercel (ADR 0003). No
  disk writes, ever (a test enforces it).
- **Demo runs execute for real** (ADR 0009): `world/scenarios/*.json` → `scenarios/runner.py`
  → `workspace/dispatch.py`. Live mode: `agent/live.py` (Claude tools = workspace routes).
- **Catalog** (ADR 0007): `catalog/action_tags.json` → `scripts/build_catalog.py` →
  `catalog/actions.csv` (139 ids), embedded on Unbox as `actions`. The ids appear in
  `catalog/unbox.json`.

## Commands

- `uv sync`: install (Python 3.12)
- `uv run uvicorn server:app --port 8780`: run it (port 8765 is taken on this machine)
- `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`: run before committing
- `uv run python scripts/make_runs.py --seed 1`: record approved runs + the eval run (monitor off)
- `uv run python -m monitor.calibrate`: fit and evaluate the step model on those runs
- `uv run python scripts/build_catalog.py`: regenerate the catalog after changing tags or vocab
- `uv run python scripts/catalog_sync.py status|push --keywords|smoke`: the catalog on Unbox
- `uv run python scripts/world/build_seed.py`: rebuild `world/seed/state.json` after editing `world/`

## Rules

- World content is data: companies, accounts, rules, scenarios live in `world/`, never in Python.
- Don't change the workspace event shape (docs/event-contract.md) without updating
  `monitor/adapter.py` and its tests.
- Secrets live in `.env` / `.env.local` (gitignored): `UNBOXAI_API_KEY`, `UNBOXAI_CATALOG_ID`,
  `ANTHROPIC_API_KEY`, `KV_REST_API_*`. Never print, log or commit them.
- Uploading a catalog sends data to Unbox AI (2 slots per key). Refresh under the same name.
- Code adapted from Unbox-AI repos is MIT. Keep their copyright notice in copied files.
- Record architecture changes as a new ADR in docs/adr/.
