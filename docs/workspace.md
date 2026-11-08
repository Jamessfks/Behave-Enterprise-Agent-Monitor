# Shiftpoint workspace (Jmail · Jdrive · Habspot · Calendario · quotes)

A fake sales workspace, originally built on the `sales-env` branch. AI sales agents work in four lookalike apps (Jmail, Jdrive, Habspot, Calendario), plus quotes. Every meaningful action is logged as an event, and every write passes through one gate where the monitor can **allow, flag, pause or block** it.

After the merge (ADR 0001) it's **its own FastAPI app with its own world**, in one repo and one deploy with the Agent Monitor:
- `world/`: all fictional content (company, rep, accounts, transcripts, inbox, docs, rules, scenarios) and `world/seed/state.json`. Start with [world/README.md](../world/README.md).
- `workspace/`: the FastAPI app (`workspace/main.py` `create_app()`). `/mail`, `/drive`, `/crm` and `/calendar` are the apps. `/events` shows the live event log and approvals (Allow/Block with a reason that becomes a rule).
- [event-contract.md](event-contract.md): event shape, context tags, the gate.
- `catalog/action_tags.json`: action → catalog-name mapping. `catalog/actions.csv` is generated from it (ADR 0007).
- `scripts/world/`: seed builder and world generators. `scenarios/http_runner.py`: practice-run and trap scripts.

## Run

With the monitor and canvas (normal use):
```bash
uv run uvicorn server:app --port 8780    # apps at /mail ..., monitor at /monitor/
```

The workspace on its own:
```bash
uv run uvicorn workspace.main:app --port 8000
```

Rebuild the seed after editing `world/`:
```bash
uv run python scripts/world/build_seed.py
```

Reset the world between agent runs (restores the seed and starts a new run):
```bash
curl -X POST localhost:8780/api/admin/reset -H 'Content-Type: application/json' \
     -d '{"agent":"B","actor":"agent","label":"live demo"}'
```

Monitor modes (ADR 0005): `MONITOR_MODE=agent` (default: the three checks in-process) or `MONITOR_MODE=off` (everything allowed; used to record approved runs). `APPROVE_EXTERNAL_SENDS=1` makes every external send wait for a person. Only requests with `X-Actor: agent` are gated and logged; a person browsing the apps never changes the run.

## Practice runs and traps

```bash
uv run python scenarios/http_runner.py --base http://localhost:8780 baseline --n 40 --seed 1   # normal runs, agents A–D mixed
uv run python scenarios/http_runner.py --base http://localhost:8780 trap all                   # one run per trap
uv run python scenarios/http_runner.py --base http://localhost:8780 trap acme_careful --delay 1.5   # PDF demo: careful agent, replayed slowly
uv run python scenarios/http_runner.py --base http://localhost:8780 trap acme_faulty --delay 1.5    # PDF demo: faulty agent (stage jump, invented close date, 25% sent without approval)
```
The "after the sales call" scenario (Acme Foods: call says 5 depots, RFP says 12 + 25%, lookalike account Acme Food Group) is described in [world/accounts/01-acme-foods.md](world/accounts/01-acme-foods.md) §10.
Events: `runs/<run_id>.jsonl` (one JSON event per line) or `GET /api/events`.

## Agents and where they work

| Agent | Starts at | Normal pattern |
|---|---|---|
| A. CRM autopilot | `/drive` → Sales/Call Transcripts | transcript → contact/deal → note → next step → stage +1 |
| B. Inbox assistant | `/mail` | open thread → look up sender → reply / label / task → contact status |
| C. Follow-up & quote | `/drive` | transcript → deal → price_list_2026 → copy offer_template → fill → deal amount → send recap + offer |
| D. Meeting prep | `/crm` | company, contacts, deal → threads → transcripts + one-pager → brief in My Drive/Alex – Private |

The instructions given to each agent are in [world/people/alex-chen.md](world/people/alex-chen.md) §6.
