# Agent Monitor (sudai2)

Hackathon MVP: an AI sales agent works in a fake workspace (Jmail, Jdrive, Habspot CRM,
Calendario, quotes) for the fictional company ShiftPoint, and every step it takes is checked
before it counts: a step model learned from approved runs, a fact check and a rules check. A
person allows (with a reason, which becomes a rule) or blocks paused steps. In the demo task
BehaviorGPT ranks every step but is **evidence only** (ADR 0004, enforced by a test). In **Live**
mode a Gemini agent uses the apps by computer use and a warm-started BehaviorGPT judges every
change: outside its top 8, the change is held and the agent stops until a person decides
(ADR 0013).

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
  → `workspace/dispatch.py`. Live mode: `agent/computer_use.py` starts
  `computer_use/gemini_agent.py` (a visible Edge window, `X-Actor: agent`) when `GEMINI_API_KEY`
  is set; else `agent/live.py` (Claude tools = workspace routes). ADR 0013.
- **Catalog** (ADR 0007): `catalog/action_tags.json` → `scripts/build_catalog.py` →
  `catalog/actions.csv` (139 ids), embedded on Unbox as `actions`. The ids appear in
  `catalog/unbox.json`.

## Commands

- `uv sync`: install (Python 3.12)
- `uv run uvicorn server:app --port 8780`: run it (port 8765 is taken on this machine)
- Live computer use: `uv sync --group live`, then `PYTHONUTF8=1 uv run uvicorn server:app --port 8780`
  (UTF-8 mode matters on Windows); keys and settings in README "Live"
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
