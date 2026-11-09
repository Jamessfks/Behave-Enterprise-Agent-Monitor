# Agent Monitor

AI agents are starting to do routine work in the same business software people use. Agent Monitor
checks every step an agent takes **before it counts**:

1. **Is this step normal?** A model learned from the company's own approved runs scores how
   likely the step is, given everything before it. BehaviorGPT (Unbox AI) also ranks every step.
   In the demo task its rank is shown as **evidence** and never changes a decision: cold, it
   ranks the true next step at a median of #78 of 139 (`results/go_no_go.json`). In **Live** mode
   it is warm-started on the company's approved runs and **judges** every change (see below).
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

## Live: an AI agent using the computer, judged by BehaviorGPT

Pick **Live**, type any request (the Acme follow-up is prefilled) and press **Run the agent**.
The demo task is unchanged; everything below applies to Live only.

- **A Gemini agent uses the apps like a person.** A visible Edge window opens on the ShiftPoint
  workspace; the agent looks at screenshots and clicks, types and scrolls (red rings show its
  clicks). Its browser identifies as the agent (`X-Actor: agent`), so every page it opens and
  every form it submits goes through the same gate as the demo task, and the canvas draws each
  step as it happens.
- **BehaviorGPT predicts every step.** Before each step counts, BehaviorGPT ranks all 139 actions
  given the run so far, warm-started with three approved runs about the same account, and the
  canvas shows where the actual step landed and its top guesses.
- **BehaviorGPT stops the agent.** If a change the agent tries is outside BehaviorGPT's top 8,
  the change is held, a pop-up on the canvas says what BehaviorGPT expected instead, a red notice
  covers the agent's window, and the agent waits. **Allow** (with a reason) lets it continue;
  **Block** stops the agent. The step model, fact check and rules check still pause steps too.

How good is BehaviorGPT at this? Measured on the company's own runs (24 approved runs and the
run with 5 planted mistakes, `docs/adr/0013-live-computer-use-and-warm-behaviorgpt.md`):

| BehaviorGPT setting | Rank of what the agent really did next (of 139) | Planted mistakes caught at cutoff top 8 | Correct changes held |
|---|---|---|---|
| Cold (the demo task) | median 86, every step | n/a | n/a |
| Warm, 3 generic approved runs | median 55, changes only; mistakes ranked 5-62, *better* than correct ones | n/a | n/a |
| **Warm, 3 runs about the same account (Live)** | **median 3, changes only** | **4 of 5** | **22 of 86** |

So in Live, expect about one false alarm for every four correct changes: a person clicks Allow
and the agent carries on. Tune it with `LIVE_BGPT_CUTOFF`.

Live needs this machine (a browser) and two keys; it is off on Vercel:

```bash
uv sync --group live
```

```bash
PYTHONUTF8=1 uv run uvicorn server:app --port 8780
```

| Setting (`.env`) | What it does |
|---|---|
| `GEMINI_API_KEY` | Turns Live on with the computer-use agent (else Live uses Claude tools, if `ANTHROPIC_API_KEY` is set) |
| `UNBOXAI_API_KEY` | BehaviorGPT calls |
| `LIVE_UNBOXAI_CATALOG_ID` | The catalog Live's BehaviorGPT uses (else `UNBOXAI_CATALOG_ID`); same 139 actions |
| `LIVE_BGPT_CUTOFF` | Hold a change ranked outside BehaviorGPT's top N (default 8) |
| `BGPT_WARM_START` | Approved example runs sent before the live run (default 3) |
| `COMPUTER_USE_MODEL` | Default `gemini-3.5-flash-lite` (about 1-2 s per action); `gemini-3.8-flash` is smarter but was overloaded in testing |

`PYTHONUTF8=1` matters on Windows only (the world files are UTF-8). The agent's log is in
`.untracked/computer_use_<run>.log`.

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
- `GEMINI_API_KEY`: **Live** mode with the computer-use agent (above).
- `ANTHROPIC_API_KEY`: **Live** mode with a Claude agent that calls the apps' routes as tools,
  when no Gemini key is set.

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
