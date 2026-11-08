# Plan: catalogs on the Unbox portal

Goal: the catalogs Agent Monitor uses are on [portal.unboxai.com/catalogs](https://portal.unboxai.com/catalogs/),
kept in sync with `catalog/actions.csv`, and anyone on the team can see which one the app uses.

## How the portal works (from the SDK docs, `behaviorgpt` 0.10.0)

- A catalog embedded with an API key **is** that account's portal catalog. There's no separate
  portal upload.
- Each key holds **2 catalogs**. The parquet's file name is the catalog's name. The same name
  refreshes that catalog and keeps its `catalog_id`; a new name takes a free slot; with both
  slots used, a new name is refused. Deleting frees a slot and can't be undone.
- Keywords (`add_keywords`) power sections and autocomplete; `embed` doesn't make them by default.

## Done (2026-11-08)

1. **`actions` is on the portal**: `cat_7c9916ba8e6b222d1084c033`, 60 actions, ready, keywords
   generated. Slot 1 of 2. Recorded in `catalog/unbox.json` (committed).
2. **One sync command**, `scripts/catalog_sync.py`:
   - `status`: the account's catalogs, slots used, which one the app uses
   - `push [--csv] [--name] [--keywords]`: validates, refuses a new name when both slots are
     full, embeds, and updates `catalog/unbox.json` and `UNBOXAI_CATALOG_ID`
   - `keywords`, `smoke`
3. **In the app** (Company & catalog drawer): "Your catalogs on the Unbox portal" lists them with
   status and slots. Uploads take a catalog name and use the same slot rule (HTTP 409 when full).
4. Tests: the slot rule, the catalogs endpoint without a key, and catalog-name validation.

## Workflow for the team

- After editing `catalog/actions.csv`, run
  `uv run python scripts/catalog_sync.py push --keywords`. Same name, so it refreshes in place
  with the same id. Then run `uv run python -m monitor.go_no_go` and
  `uv run python -m monitor.calibrate`, because rankings may change. Commit `catalog/unbox.json`,
  `runs/rankings_cache.json` and `monitor/calibration.json`.
- The second slot is free for a company's own catalog uploaded from the UI (default name
  `company_actions`).

## Needs your decision

- **Rename `actions`** to something clearer on the portal (e.g. `agent_monitor_acme_actions`):
  push under the new name (uses slot 2), point the app at it, then delete `actions`. The delete is
  permanent, and it leaves no free slot for a company upload.
- **Register Agent Monitor as a portal app** (portal Home → "Add an app"), so it opens from the
  portal on the selected catalog (`?catalog_id=`). This needs a production URL without Vercel's
  deployment protection, and the app should read `catalog_id` from the query.
- **Item images**: the portal shows item pictures, and ours are text-only. Icons would have to be
  hosted somewhere Unbox's servers can fetch (not a protected Vercel preview).
- **Verify on the page**: the portal needs your sign-in (email link or API key) to show the
  Catalogs page. Sign in in the browser pane and it can be checked there.
