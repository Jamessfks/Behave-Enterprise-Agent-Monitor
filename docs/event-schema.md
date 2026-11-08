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
| `details.app` | string | `Inbox`, `Docs`, `Transcripts`, `CRM`, `Email` |
| `details.entity` | string \| null | The company the action is about. Drives the wrong-client check |
| `details.irreversible` | bool | `true` for actions the monitor must check **before** they execute (sending email, deleting) |
| `details.*` | any | Anything else, for display only. `details` is **never sent to the model** |

### Why there's no `order` type

The draft schema had `search | view | order`. We dropped `order`. Upstream scoring never scores
orders (it treats them as checkout of items already chosen), and our riskiest actions (send,
delete) are exactly the ones that must be scored. Every action is a `view`. Irreversibility is the
`details.irreversible` flag, which the monitor uses to gate execution, not to rank.

## Monitor result per step (monitor → UI)

Pushed over Server-Sent Events at `GET /api/runs/{run_id}/stream`, one message per agent event.

```json
{
  "run_id": "golden_01",
  "step": 8,
  "status": "scored",
  "action_id": "crm.create_lead_record",
  "p": 0.031,
  "rank": 7,
  "u": 2.4,
  "cusum": 3.1,
  "risk": 0.62,
  "flagged": false,
  "expected": [{"action_id": "crm.log_activity", "name": "Log an activity on the lead", "p": 0.41}],
  "reasons": []
}
```

| Field | Rules |
|---|---|
| `status` | `scored` (first touch of an action), `context` (a search), `funnel` (repeat of an action already taken; not scored) or `unknown` (id not in the catalog) |
| `p`, `rank`, `u` | Only for `scored`. `rank` is 1-based within the catalog |
| `cusum`, `risk` | Running values after this step. `risk = cusum / barrier`; ≥ 1.0 means flagged |
| `flagged` | `true` from the first step where risk ≥ 1.0 until a human approves |
| `expected` | Top 3 actions the model predicted for this step |
| `reasons` | Human-readable strings for the alert card |

## Control messages (UI → monitor → agent)

- `POST /api/runs/{run_id}/approve`: resets `flagged` and lets the agent continue. The CUSUM is
  reset to 0 and history is kept.
- `POST /api/runs/{run_id}/stop`: ends the run. The agent loop exits.
- `POST /api/runs/{run_id}/gate` with the would-be event: called by the **environment** before it
  executes an irreversible action (e.g. the Send button handler). The monitor scores the event as if
  it had happened and returns `{"allow": bool, "risk": float, "reasons": [...]}`. If
  `allow` is false, the environment shows "Waiting for approval" and doesn't send. Gating in the
  environment rather than the agent loop means it works whichever agent does the clicking.
