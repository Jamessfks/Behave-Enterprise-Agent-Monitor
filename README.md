# Agent Monitor

AI agents are starting to do routine work in the same business software people use. Agent Monitor
checks every step an agent takes **before it counts**:

1. **Is this step normal?** A model learned from the company's own approved runs scores how
   likely the step is, given everything before it. BehaviorGPT (Unbox AI) also ranks every step
   live. Its rank is shown as **evidence** and never changes a decision: on this workflow it
   ranks the true next step at a median of #78 of 139 (`results/go_no_go.json`).
2. **Is this fact true?** Every value the agent typed must appear in a source it opened, and an
   amount must follow from the stated locations and the price list.
3. **Is this allowed?** Written policies, a senior rep's unwritten rules, and rules people taught
   it.

If a check fails on a write, the agent pauses. A person sees why and clicks **Allow** (with a
reason, which becomes a rule) or **Block**. Allowed steps really change the apps; blocked ones
change nothing.

## The demo

ShiftPoint (fictional) sells shift-scheduling software. Its agent does the follow-up after Friday's
call with Acme Foods: CRM updates, a quote, a recap. It works in a fake workspace (Jmail, Jdrive,
Habspot CRM, Calendario, quotes), shown live next to the monitor.
- **Run the agent** with **Plant mistakes** off: no pauses. Habspot shows the deal in Demo with
  the call note, Jdrive has the quotes, Jmail has the question to Alex, the approval request to
  Dana and the recap draft, and Calendario has the CFO call.
- With **Plant mistakes** on: it flags opening the lookalike company and pauses 4 times:
  - stage jump (rules)
  - invented close date (facts)
  - an amount for 12 depots at 25% (facts + rules)
  - sending the 25% quote without approval (step model + facts + rules)

Details: [docs/workflow.md](docs/workflow.md), [world/accounts/01-acme-foods.md](world/accounts/01-acme-foods.md).

## Run it

```bash
uv sync
```

```bash
uv run uvicorn server:app --port 8780
```

Open <http://localhost:8780>. It redirects to the monitor at `/monitor/`; the apps are at `/mail`,
`/drive`, `/crm` and `/calendar`. No API keys are needed: BehaviorGPT's rankings for the demo are
cached in `runs/rankings_cache.json`.

Optional keys in `.env` (copy `.env.example`):
- `UNBOXAI_API_KEY` and `UNBOXAI_CATALOG_ID`: live BehaviorGPT, plus the Unbox catalog tools.
- `ANTHROPIC_API_KEY`: **Live** mode, where a Claude agent works on any request you type, through
  the same gate.

## How it's built

Two FastAPI apps, one deploy:
- **The ShiftPoint workspace** (`workspace/`, its own app over its own world in `world/`, from
  the `sales-env` branch). Every write goes through one gate.
- **The monitor** (`server.py`, `monitor/`, `scenarios/`, `agent/`, `web/`), which checks each
  step at that gate in-process.

State lives in process memory locally and in Upstash Redis on Vercel. Every decision is an ADR in
[docs/adr/](docs/adr/README.md).

## Deploy on Vercel

`vercel deploy`. The project needs `KV_REST_API_URL` / `KV_REST_API_TOKEN` (Upstash, from the
Vercel Marketplace) and optionally the keys above.

## Develop

```bash
uv run pytest -q
```

```bash
uv run ruff check . && uv run ruff format --check .
```

- `uv run python scripts/make_runs.py --seed 1`: record the approved runs and the eval run
- `uv run python -m monitor.calibrate`: fit the step model and evaluate it on the eval run
- `uv run python -m monitor.go_no_go`: BehaviorGPT transfer test, and rebuild its rankings cache
- `uv run python scripts/build_catalog.py`: regenerate `catalog/actions.csv` (139 actions)
- `uv run python scripts/catalog_sync.py status|push --keywords|smoke`: the catalog on the
  [Unbox portal](https://portal.unboxai.com/catalogs/)
- `uv run python scripts/world/build_seed.py`: rebuild the world seed after editing `world/`

The scoring method is adapted from Unbox AI's
[behaviorgpt-anomaly](https://github.com/Unbox-AI/behaviorgpt-anomaly) (MIT).
