# Shared event schema (draft — confirm in Phase 0)

Every part of Sentinel speaks this format. Environment → monitor → UI. Change it only together with
every consumer.

```json
{
  "run_id": "run_2026-11-08T15-02-11_a1",
  "step": 4,
  "timestamp": "2026-11-08T15:03:40.512Z",
  "type": "view",
  "action_id": "crm.create_record",
  "query": null,
  "details": {"entity": "Acme Corp", "app": "CRM", "source": "env"}
}
```

| Field | Rules |
|---|---|
| `run_id` | one per agent session |
| `step` | 0-based, strictly increasing within a run |
| `timestamp` | ISO-8601 UTC |
| `type` | `search` \| `view` \| `order`. Maps to BehaviorGPT `Search` / `View` / `Order` |
| `action_id` | id from `catalog/actions.csv`. Required for `view`/`order`, null for `search` |
| `query` | search text. Required for `search`, null otherwise |
| `details` | free-form, for display and explanations only. **Never sent to the model.** Put the entity (client/company) here so a content check can catch "right steps, wrong client" |

## Monitor output per step (monitor → UI)

```json
{
  "run_id": "...", "step": 4,
  "status": "scored",
  "p": 0.031, "rank": 7, "u": 2.4,
  "cusum": 3.1, "risk": 0.62, "flagged": false,
  "expected": [{"action_id": "docs.search_company", "p": 0.41}],
  "reasons": ["Created a CRM record before looking up the company."]
}
```

`status` is one of `scored`, `context` (searches), `funnel` (repeat of an already-touched action)
or `order`. Only `scored` steps have p/rank/u.
