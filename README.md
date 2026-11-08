# Agent Monitor

AI agents are starting to do routine work in the same business software people use. Agent Monitor
checks every step an agent takes **before it counts**:

1. **Is this step normal?** A model learned from the company's own approved runs scores how
   likely the step is, given everything before it, and decides when to pause. BehaviorGPT
   (Unbox AI) also ranks every step live. Its rank is shown as **evidence** and doesn't change
   any decision: on this workflow it ranked the correct next step at a median of #21 of 60, and
   it rates "send the quote" as the #2 most likely step (`results/behaviorgpt_audit.json`).
2. **Is this fact true?** Every value the agent typed must appear in a source it opened.
3. **Is this allowed?** Written policies, a senior rep's unwritten rules, and rules people taught
   it.

If any check fails, the agent pauses. A person sees why and clicks **Allow** (with a reason, which
becomes a rule) or **Block**.

The demo is a fictional sales team: NovaDesk's follow-up after a discovery call with Acme
Industries. A careful agent and a faulty agent get the same task, and the faulty one makes three
planted mistakes (see [docs/workflow.md](docs/workflow.md)).

## Run it (under a minute)

```bash
uv sync
```

```bash
uv run uvicorn server:app --port 8780
```

Open <http://localhost:8780>, pick **Careful agent** or **Faulty agent**, and press **Play**. No
API keys are needed for the recorded runs: BehaviorGPT's rankings for them are cached in
`runs/rankings_cache.json`.

Optional keys in `.env` (copy `.env.example`):
- `UNBOXAI_API_KEY` and `UNBOXAI_CATALOG_ID`: live BehaviorGPT, plus catalog upload and embedding
  from the UI.
- `ANTHROPIC_API_KEY`: **Live** mode, where a Claude agent works on any request you type.

## Deploy on Vercel

The app is one stateless FastAPI function (`server.py`), with `web/` served from the CDN. Set the
same environment variables in the Vercel project, then run `vercel deploy`.

## Develop

```bash
uv run pytest -q
```

```bash
uv run ruff check . && uv run ruff format --check .
```

- `uv run python scripts/make_scripted_runs.py`: regenerate the runs
- `uv run python -m monitor.go_no_go`: BehaviorGPT transfer test → `results/go_no_go.json`
- `uv run python -m monitor.calibrate`: fit and evaluate the step models →
  `monitor/calibration.json`
- `uv run python scripts/catalog_sync.py status|push|keywords|smoke`: the catalog on the
  [Unbox portal](https://portal.unboxai.com/catalogs/); see [docs/plans/unbox-portal-catalogs.md](docs/plans/unbox-portal-catalogs.md)

Why the default step model isn't BehaviorGPT alone, and the other design decisions:
[docs/decisions.md](docs/decisions.md).

The scoring method is adapted from Unbox AI's
[behaviorgpt-anomaly](https://github.com/Unbox-AI/behaviorgpt-anomaly) (MIT).
