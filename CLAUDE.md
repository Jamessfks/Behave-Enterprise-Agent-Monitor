# Agent Monitor (sudai2)

Hackathon MVP: every step an AI sales agent takes is checked before it counts (step model incl.
BehaviorGPT, fact check, rules check); a person allows or blocks paused steps. Stateless FastAPI
(`server.py`) + plain JS canvas (`web/`), deployable on Vercel. See README.md to run it.

## Read first

- [docs/PROJECT.md](docs/PROJECT.md): brief, architecture, phased task list
- [docs/workflow.md](docs/workflow.md): the one demo workflow, its correct steps and injected mistakes
- [docs/event-schema.md](docs/event-schema.md): the shared event format (env → monitor → UI)
- [docs/decisions.md](docs/decisions.md): go/no-go results, step models, stateless/Vercel, open items
- [docs/prompts/build-mvp.md](docs/prompts/build-mvp.md): the build spec (Agent Monitor PDF)
- [docs/reference/behaviorgpt.md](docs/reference/behaviorgpt.md): BehaviorGPT SDK, catalog format, limits
- [docs/reference/anomaly-method.md](docs/reference/anomaly-method.md): scoring method (Unbox's anomaly detector, adapted)
- [docs/reference/computer-use.md](docs/reference/computer-use.md): Claude computer-use toolset (for a later computer-use mode)

## Layout

`env/` scenario, company context, app tools · `monitor/` the three checks, rankers, calibration ·
`agent/live.py` Claude loop · `server.py` API · `web/` UI · `runs/` scripted runs + BehaviorGPT
cache · `catalog/actions.csv` the 60 actions.

## Commands

- `uv sync`: install (Python 3.12, `behaviorgpt` 0.10.0)
- `uv run uvicorn server:app --port 8765`: run the app
- `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`: run before committing
- `uv run python scripts/make_scripted_runs.py`: regenerate `runs/*.jsonl` from the workflow

## Project skills (`.claude/skills/`)

- `action-catalog`: write, edit, validate and embed `catalog/actions.csv`
- `go-no-go`: the first-hour transfer test (does BehaviorGPT rank our workflow well?)
- `monitor-scoring`: probability → excess surprisal → CUSUM → threshold → explanations

## Rules

- Keep it simple: this is a few-hour demo. Favor replayable, deterministic pieces, and cache every
  BehaviorGPT response on disk.
- Don't change the event schema without updating every consumer.
- Secrets live in `.env` (gitignored): `UNBOXAI_API_KEY`, `UNBOXAI_CATALOG_ID`, `ANTHROPIC_API_KEY`.
  Never print, log or commit them.
- Uploading a catalog sends data to Unbox AI, and each key has only 2 catalog slots. Confirm with
  the user before `client.embed`.
- Live agent: `claude-opus-5-5` with the app tools in `env/app.py` (not computer use).
- After changing runs or rankers: `uv run python -m monitor.calibrate`, then the tests.
- Code adapted from Unbox-AI repos is MIT. Keep their copyright notice in copied files.
