# BehaviorGPT SDK — what Sentinel needs

Condensed from the SDK's own docs ([Unbox-AI/behaviorgpt](https://github.com/Unbox-AI/behaviorgpt),
MIT, v0.10.0 on PyPI as of 2026-11-08). The upstream README and
[`docs/catalog-format.md`](https://github.com/Unbox-AI/behaviorgpt/blob/main/docs/catalog-format.md)
are the source of truth. Check them if anything here disagrees with what the SDK does.

## Setup

```sh
pip install behaviorgpt        # Python 3.11+
export UNBOXAI_API_KEY=...     # free key from portal.unboxai.com; keep it in .env, never commit it
```

```python
from behaviorgpt import UnboxAIClient, Search, View, Order
client = UnboxAIClient(market="us", default_catalog_id="cat_...")  # or UNBOXAI_CATALOG_ID
```

`AsyncUnboxAIClient` has the same methods, awaited. Use it inside a FastAPI server, create one
client and reuse it for the server's lifetime.

## The one call: `complete`

```python
res = client.complete(history, limit=10, catalog_id=..., filters=None, register_event=False)
res.items   # ranked; each has .id, .score (raw ranking score, NOT a probability), .data (catalog row)
res.names   # convenience list of names
```

It answers: given this history (oldest first), which catalog item is acted on next?

- `filters={"id": [ids...]}` restricts the ranking to those ids and returns their scores. This is how
  you get the score of the action the agent *actually* took, even when it isn't in the top N.
- `limit` caps the result count. One call holds up to 100 ids in an `id` filter.
- `predict="purchase"` asks "what goes in the same purchase". Not useful for Sentinel.
- `register_event=False` keeps calls from being stored as user events.

## Events (the history)

| SDK | Meaning in a store | Sentinel mapping (proposed) |
|---|---|---|
| `Search("query")` | a query | the agent searched (inbox search, doc search, CRM lookup), with the query text |
| `View(item_id)` | any sign of interest in an item | the agent performed catalog action `item_id` |
| `Order([item_id, ...])` | a finished purchase | an irreversible commit (email sent, record saved) |

Also exported: `AddToCart`, `RemoveFromCart`, `ExternalItem` (an item described by name/image
that isn't in the catalog), `User` (market, gender, age group, timezone; all optional).

**The model ranks items already seen in the history low on purpose.** Repeating the same item looks
surprising. Design the action catalog so that a normal run touches each item about once (see
[anomaly-method.md](anomaly-method.md)).

## Catalog: the action list as "items"

The model reads each item from its **content** (name, brand, categories, image, price), not its id.
That's why it can rank a catalog it has never seen. For Sentinel, each item is a workplace action.

A parquet with these 15 columns is required. In a CSV, only the ones in **bold** need values:

| Column | Type | Sentinel use |
|---|---|---|
| **`id`** | string, unique | action id, e.g. `crm.create_record` |
| **`name`** | string | plain-language action, e.g. "Create a new lead record in the CRM". This is the main signal |
| `brand` | string | app name: `Inbox`, `Docs`, `CRM` |
| `categories` | string, comma-separated, general → specific | e.g. `Sales, CRM, Write` |
| `image_url` | public https URL | optional (e.g. an app icon). Null means a text-only embedding |
| **`event_type`** | string | always `product` |
| **`group`** | string | always `product` |
| `sales_since` | list of 12 int64 | popularity. Leave null unless we have run counts |
| `timestamp`, `frequency` | int64 | popularity/recency. Can be null |
| `market`, `price`, `currency`, `search_keywords`, `keywords` | | null is fine |

Convert and upload:

```python
from behaviorgpt import catalog_from_csv
path = catalog_from_csv("catalog/actions.csv")          # writes catalog/actions.parquet, validates
job = client.embed(path, wait=True, timeout=1800.0)     # takes minutes; file name = catalog name
print(job.catalog_id)                                   # cat_...
```

Limits: 100,000 items per catalog and **2 catalogs per API key**. Re-uploading the same file name
refreshes that catalog and keeps its id, so always reuse the name `actions.parquet`.
`client.add_items(path, catalog_id=..., wait=True)` adds or replaces a few items without a full
re-embed.

The image rule: if none of the first 500 *fetched* images is usable, the job fails. With every
`image_url` null, the embedding is built from text, and the docs say that's valid. If we add icons,
host them on a public https host that allows plain server fetches.

## Errors

`UnboxAIError(message, status_code, response)` with subclasses `AuthenticationError` (401),
`BadRequestError` (400) and `RateLimitError` (429). Retry 429/5xx with backoff. The upstream
anomaly app retries `{429, 500, 502, 503, 504}` and caches every ranking on disk keyed by
(catalog, history, limit, filters). Do the same, since the demo replays the same prefixes.

## Other entry points (not needed for v1)

- Raw REST: `https://behaviorgpt-northeurope.api.unboxai.com/v1`, header `x-api-key`.
- Portal shop API: `https://portal.unboxai.com/api/v1/shop/` with a Bearer key.
- MCP server: `https://portal.unboxai.com/mcp`.
- Agent-oriented docs: `https://portal.unboxai.com/llms.txt`.
