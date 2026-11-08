---
name: action-catalog
description: Create, edit, validate and embed Sentinel's workplace action catalog (catalog/actions.csv) for BehaviorGPT. Use when adding, renaming or removing an action, writing the catalog for the first time, converting it to parquet, or uploading it with client.embed / add_items.
---

# Sentinel action catalog

The catalog is the list of workplace actions BehaviorGPT ranks. Each row is one semantic action
the agent can take in the fake environment. Read `docs/reference/behaviorgpt.md` (columns, limits)
and `docs/reference/anomaly-method.md` (why granularity matters) first.

## Files

- `catalog/actions.csv`: the source of truth, committed.
- `catalog/actions.parquet`: generated, gitignored. Its file name is the catalog name upstream,
  so never rename it, or it takes the key's second (and last) catalog slot.
- `.env`: `UNBOXAI_API_KEY`, `UNBOXAI_CATALOG_ID`. Never print or commit the key. If it's missing,
  ask the user to add it to `.env` themselves, not to paste it in chat.

## Writing an action row

| Column | Value |
|---|---|
| `id` | `<app>.<verb>_<object>`, e.g. `inbox.open_lead_email`, `crm.create_record`, `email.send_quote` |
| `name` | One plain sentence, as a person would describe doing it: "Send the customer a price quote by email". **This is the main signal the model reads**, so write it for meaning, not UI mechanics |
| `brand` | The app: `Inbox`, `Docs`, `Transcripts`, `CRM`, `Email` |
| `categories` | General → specific: `Sales, CRM, Write` |
| `event_type`, `group` | `product` (required literal) |
| everything else | leave empty |

Rules:
- **Action × object, not UI verbs.** A correct run should touch each action about once, because the
  model ranks repeats low and the scorer skips them. "Click button" or "type text" are wrong.
- **Include plausible wrong actions** (~⅓ of rows) that a confused agent might take: send the quote
  before the lookup, update the wrong record, delete a record, email the wrong contact. They make
  the mistake run scoreable and keep the catalog realistic.
- Searches are not rows. They're `Search(query)` events.
- Keep 30–60 rows. With ≤100 rows, one `complete(limit=N)` call ranks the whole catalog.

After adding or renaming an action, also update:
1. The environment code that emits that `action_id` (grep for the id).
2. `docs/event-schema.md` examples if they mention it.
3. The recorded runs in `runs/` if they use a renamed id. Then recalibrate (see the
   `monitor-scoring` skill).

## Build and validate

```python
from behaviorgpt import catalog_from_csv
path = catalog_from_csv("catalog/actions.csv")   # writes catalog/actions.parquet, runs schema check
```

Before converting, check: ids unique, no empty `id`/`name`, every id used in the environment
exists in the CSV (`grep -rhoE '"(inbox|docs|transcripts|crm|email)\.[a-z_]+"'` against the CSV).

## Upload (sends data to Unbox; confirm with the user first)

```python
from dotenv import load_dotenv; load_dotenv()
from behaviorgpt import UnboxAIClient
client = UnboxAIClient(market="us")
job = client.embed("catalog/actions.parquet", wait=True, timeout=1800.0)   # minutes; run in background
print(job.catalog_id)   # → put in .env as UNBOXAI_CATALOG_ID
```

For a few new or changed rows on an existing catalog, build a parquet of just those rows and use
`client.add_items(path, catalog_id=..., wait=True)`.

On `UnboxAIError`, the message has the server's reason (`client.job_status(job.job_id).error`).

## Smoke test

```python
from behaviorgpt import Search, View
print(client.complete([Search("new inbound lead")], limit=5).names)
print(client.complete([View("inbox.open_lead_email")], limit=5).names)
```

The second list should look like sensible next steps of the workflow. If it doesn't, rewrite the
`name`s before blaming the model.
