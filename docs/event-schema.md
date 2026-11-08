# Shared event schema

**Status: decided (Phase 0, 2026-11-08).** Every part of Sentinel speaks this format: environment →
monitor → UI. Change it only together with every consumer.

## Agent event (environment → monitor)

The environment app emits one event per semantic action, as one JSON object per line in
`runs/*.jsonl` and as the body of `POST /api/events`.

```json
{
  "run_id": "golden_01",
  "step": 8,
  "timestamp": "2026-11-08T15:03:40.512Z",
  "type": "view",
  "action_id": "crm.create_lead_record",
  "query": null,
  "details": {"app": "CRM", "entity": "Northwind Robotics", "irreversible": false}
}
```

| Field | Type | Rules |
|---|---|---|
| `run_id` | string | One per agent session |
| `step` | int | 0-based, strictly increasing within a run, no gaps |
| `timestamp` | string | ISO-8601 UTC with milliseconds and `Z` |
| `type` | `"search"` \| `"view"` | `search` → BehaviorGPT `Search(query)`. `view` → `View(action_id)` |
| `action_id` | string \| null | A catalog id (`catalog/actions.csv`). Required for `view`, null for `search` |
| `query` | string \| null | Required for `search`, null for `view` |
| `details.app` | string | `Mail`, `Files`, `Calls`, `CRM`, `Quotes`, `Chat`, `Calendar` |
| `details.entity` | string \| null | The company the action is about. Drives the wrong-client check |
| `details.irreversible` | bool | `true` for actions the monitor must check **before** they execute (sending email, deleting) |
| `details.values` | object | What the agent typed: `{field: value}`. The fact check verifies these (`seats`, `close_date`, `amount`, …) |
| `details.source` | string | Source id the step opened (`call_acme`, `email_acme`, …). Opened sources are what the fact check may cite |
| `details.driver` | string | `scripted` or `claude` |
| `details.decision` | string | `allow` / `block`, set after a person decided on a paused step |
| `details.*` | any | Anything else, for display only. `details` is **never sent to the model** |

### Why there's no `order` type

The draft schema had `search | view | order`. We dropped `order`. Upstream scoring never scores
orders (it treats them as checkout of items already chosen), and our riskiest actions (send,
delete) are exactly the ones that must be scored. Every action is a `view`. Irreversibility is the
`details.irreversible` flag, which the monitor uses to gate execution, not to rank.

## Checking a step (browser or agent loop → server)

The server is stateless. Before a step runs, the caller sends the run so far:

`POST /api/check` with `{history, event, context?, cusum, ranker?}` returns:

```json
{
  "step": 12, "action_id": "crm.set_close_date", "name": "Set the expected close date on the deal",
  "verdict": "pause",
  "failed": ["facts"],
  "headline": "“close date = 2026-12-31” appears in no source the agent opened.",
  "reasons": ["..."],
  "precedent": null,
  "ranker": "workflow",
  "checks": {
    "normal": {"ok": true, "status": "scored", "p": 0.31, "rank": 2, "u": 0.1, "cusum": 0.0,
               "risk": 0.0, "barrier": 8.7, "expected": [{"action_id": "...", "name": "...", "p": 0.4}],
               "missing": [], "behaviorgpt": {"rank": 26, "of": 60, "top": [{"action_id": "...", "name": "..."}]}},
    "facts":  {"ok": false, "checked": [{"field": "close_date", "value": "2026-12-31", "ok": false, "evidence": []}],
               "warnings": []},
    "rules":  {"ok": true, "violations": [], "precedents": []}
  },
  "latency_ms": {"normal": 0.8, "facts": 0.3, "rules": 0.0}
}
```

- `verdict`: `pass`, `pause` (a person decides) or `allowed_by_rule` (a learned precedent covers
  every failed check).
- `checks.normal.status`: `scored` (first touch of an action), `context` (a search), `funnel`
  (repeat; not scored) or `unknown`.
- The caller keeps `cusum` from `checks.normal.cusum` after a pass, and resets it to 0 after a
  person decides.

## Decisions (UI → server)

- **Allow** needs a reason: `POST /api/rules/learn` with `{event, failed, reason}` returns a
  `precedent` rule, which the caller adds to `context.learned_rules`.
- **Block**: the step never runs. In live mode the agent gets "Blocked by a supervisor: <reason>".
