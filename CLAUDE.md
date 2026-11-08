# Sentinel (sudai2)

Hackathon project: a behavioral oversight layer for computer-use agents doing sales workflows.
A computer-use agent works in a fake inbox/docs/CRM app, every action becomes an event, and
BehaviorGPT-based scoring pauses the agent when the run stops looking normal.

## Read first

- [docs/PROJECT.md](docs/PROJECT.md): brief, architecture, phased task list
- [docs/workflow.md](docs/workflow.md): the one demo workflow, its correct steps and injected mistakes
- [docs/event-schema.md](docs/event-schema.md): the shared event format (env → monitor → UI)
- [docs/decisions.md](docs/decisions.md): stack, deployment, agent, and open items

## Commands

- `uv sync`: install (Python 3.12, `behaviorgpt` 0.10.0)
- `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`: run before committing
- `uv run python scripts/make_scripted_runs.py`: regenerate `runs/*.jsonl` from the workflow
- [docs/reference/behaviorgpt.md](docs/reference/behaviorgpt.md): BehaviorGPT SDK, catalog format, limits
- [docs/reference/anomaly-method.md](docs/reference/anomaly-method.md): scoring method (Unbox's anomaly detector, adapted)
- [docs/reference/computer-use.md](docs/reference/computer-use.md): Claude computer-use toolset and agent loop

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
- Computer-use model: `claude-opus-5-5` with `{"type": "computer_toolset_20260801"}`.
- Code adapted from Unbox-AI repos is MIT. Keep their copyright notice in copied files.
