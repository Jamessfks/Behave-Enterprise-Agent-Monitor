# Audit: the demo vs Unbox's official documentation

**Date:** 2026-11-08. **SDK:** `behaviorgpt` 0.10.0 (latest on PyPI).

**Sources, read live:**
- the Build page, [portal.unboxai.com/build](https://portal.unboxai.com/build/): `#client`
  "Your own interface", `#server` "From your server", `#app` "Your own app", `#agents`, and the
  "Build with your AI" prompt
- [llms.txt](https://portal.unboxai.com/llms.txt)
- the SDK README and `docs/catalogs.md` / `docs/catalog-format.md` in the installed package

**Method:** each item was checked against the running demo. That meant the real HTTP payload
(captured at the SDK's transport), live API calls, and the deployed Vercel responses. Code
reading alone wasn't counted as evidence.

## Which section applies

The demo calls BehaviorGPT **from its server** (Python SDK, secret key). That's `#server`. The
`#client` section is the browser path: React hooks or `createClient` with a **publishable key**
(`ubx_pub_…`), calling from the visitor's browser. The demo never calls Unbox from the browser,
by design: every call goes through FastAPI, so `#client` rules only matter as "don't put the
secret key in a page".

## Results

| # | Official guidance | Demo | Evidence | Status |
|---|---|---|---|---|
| 1 | Key in `UNBOXAI_API_KEY`, "never in code"; the browser only gets a publishable key | Key in `.env` / Vercel Sensitive env; the browser never calls Unbox | Scanned 7 deployed responses (pages, JS, CSS, 3 API routes): no key, no `ubx_` prefix. `git grep` finds no key in tracked files | ✅ |
| 2 | `pip install "behaviorgpt>=0.8"` | 0.10.0 (latest) | `uv pip show`, PyPI | ✅ |
| 3 | `UnboxAIClient(market="us", …)` | `market="us"` | Payload `domains.market = "us"` | ✅ |
| 4 | `complete(history, limit=…)` ranks a catalog for any history | One call per step, `limit=60` (whole catalog), `catalog_id` per call | Payload: `/v1/vector/recommendations`, `store_id` = our catalog, `limit` 60, 60 items back | ✅ |
| 5 | Calls that pass a `user_id` are recorded; pass `register_event=False` to record nothing | `register_event=False`, no `user_id` | Payload `register_event: false` | ✅ |
| 6 | Use current parameter names (`catalog_id`, not `catalog`) | `catalog_id` everywhere | Code + payload | ✅ |
| 7 | "Set the time zone: the default is UTC, and the hour and weekday the model reads are then UTC's" | Was UTC (unset) | Payload `timezone: "UTC"`. The SDK stamps history events with the current time (`_client.py`) | 🔧 **Fixed**: `America/New_York` (env `UNBOXAI_TIMEZONE`). Measured impact: score change ≤ 0.0005, 0 of 23 ranks moved |
| 8 | "Create one client and reuse it" | Server created a client per request (4 places) | Code | 🔧 **Fixed**: one shared client (`monitor/unbox.get_client`) |
| 9 | Errors: `RateLimitError` (429), `UnboxAIError` | No retries | Code | 🔧 **Fixed**: retries 429/5xx twice (0.5 s, 1.5 s), never 4xx; tested |
| 10 | Catalog: parquet via `catalog_from_csv`; `event_type`/`group` = `product`; ≤ 100k items; 2 per key; same name refreshes | All followed; slot guard in UI and script | Embed job succeeded; `list_catalogs` shows `actions` ready, 1 of 2 slots | ✅ |
| 11 | Keywords via `add_keywords` for sections/autocomplete | Generated for `actions` | Job completed | ✅ |
| 12 | Async servers should use `AsyncUnboxAIClient` | FastAPI routes are sync `def` (run in a threadpool), so the sync client doesn't block the loop | Code | ✅ acceptable. Switch only if routes become `async` |
| 13 | `#app`: an app opened from portal Home gets `?catalog_id=&compare=&streams=`; https except localhost | Not wired: the UI ignores `catalog_id` | Code | ⏳ **Gap**: needs a production URL without Vercel protection, then reading `catalog_id` |
| 14 | Item images carry much of the embedding signal (`catalog-format.md`) | Text-only actions (no `image_url`) | Catalog | ℹ️ Fine for workplace actions. Names do the work |
| 15 | SDK README: the default catalog is `retail_catalog` | Not used. The demo always passes `catalog_id` | Calling without it fails with "unknown catalog: retail_catalog". This key sees `retail_catalog_500k` | ℹ️ Docs inconsistency, worth telling Unbox |

## What this audit also confirmed (from `results/behaviorgpt_audit.json`)

- **BehaviorGPT is called live:** about 0.3 s per call, 60 items each, also from the Vercel deploy
  (527 ms uncached vs 0.39 ms cached).
- **It's evidence, not a decider:** with the default ranker, verdicts are identical with BehaviorGPT
  switched off (`test_default_verdicts_do_not_depend_on_behaviorgpt`).

## Re-run

```bash
uv run python scripts/audit_behaviorgpt.py
```

```bash
uv run pytest -q
```
