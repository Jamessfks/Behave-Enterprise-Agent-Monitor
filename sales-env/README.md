# Shiftpoint sales environment (Jmail · Jdrive · Habspot)

A fake sales workspace for the **Sentinel** hackathon demo. AI sales agents (computer-use or scripted) work in three lookalike apps; every meaningful action is logged on the server as an event, and every write passes through one gate where Sentinel can **allow, flag, pause or block** it.

- `world/`: all fictional content (company, rep, accounts, transcripts, inbox, docs). Start with [world/README.md](world/README.md).
- `app/`: FastAPI app. `/mail`, `/drive` and `/crm` are the three apps; `/events` shows the live event log and approvals.
- `docs/EVENT-CONTRACT.md`: event shape, context tags, monitor hook, and **how to adapt them later**.
- `catalog/actions.json`: action → catalog-name mapping, owned by the catalog designer and hot-reloaded.
- `scripts/`: seed builder, practice-run and trap scripts.

## Run

```bash
cd sales-env
python3 -m venv .venv && .venv/bin/pip install fastapi uvicorn jinja2 python-multipart httpx markdown
.venv/bin/python scripts/build_seed.py        # world/ -> seed/state.json
.venv/bin/uvicorn app.main:app --port 8000    # open http://localhost:8000
```

Reset the world between agent runs (restores seed and starts a new run):
```bash
curl -X POST localhost:8000/api/admin/reset -H 'Content-Type: application/json' \
     -d '{"agent":"B","actor":"agent","label":"live demo"}'
```

Monitor modes (see docs/EVENT-CONTRACT.md):
```bash
MONITOR_MODE=off    .venv/bin/uvicorn app.main:app --port 8000   # default, everything allowed
MONITOR_MODE=rules  .venv/bin/uvicorn app.main:app --port 8000   # built-in stand-in rules
MONITOR_MODE=remote MONITOR_URL=http://localhost:8100/check MONITOR_FAIL=closed .venv/bin/uvicorn app.main:app --port 8000
```

## Practice runs and traps

```bash
.venv/bin/python scripts/scenarios/run.py baseline --n 40 --seed 1   # normal runs, agents A–D mixed
.venv/bin/python scripts/scenarios/run.py trap all                   # one run per trap
```
Events: `runs/<run_id>.jsonl` (one JSON event per line) or `GET /api/events`.

## Agents and where they work

| Agent | Starts at | Normal pattern |
|---|---|---|
| A. CRM autopilot | `/drive` → Sales/Call Transcripts | transcript → contact/deal → note → next step → stage +1 |
| B. Inbox assistant | `/mail` | open thread → look up sender → reply / label / task → contact status |
| C. Follow-up & quote | `/drive` | transcript → deal → price_list_2026 → copy offer_template → fill → deal amount → send recap + offer |
| D. Meeting prep | `/crm` | company, contacts, deal → threads → transcripts + one-pager → brief in My Drive/Alex – Private |

The instructions given to each agent are in [world/people/alex-chen.md](world/people/alex-chen.md) §6.
