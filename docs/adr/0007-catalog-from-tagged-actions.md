# 0007. The BehaviorGPT catalog is generated from tagged workspace actions

- **Status:** Accepted, 2026-11-08

## Context

The workspace names each action `action + ":" + context tags` (`catalog/action_tags.json`), e.g.
`habspot.stage:stage_skip` or `quote.send:over_limit:not_approved`. BehaviorGPT and the step model
rank these ids, but `action_tags.json` is a tag map, not a catalog. The old 60-row catalog
described the retired NovaDesk world.

## Decision

- **`scripts/build_catalog.py`** generates `catalog/actions.csv` from `action_tags.json` × the tag
  values the workspace can actually produce:
  - the enums come from `workspace/events.py`;
  - data-derived values (doc kinds and sensitivities, contact statuses) come from the seed;
  - impossible combinations are pruned (e.g. `quote.send` only has three valid approval pairings).
- **Readable names** from `catalog/vocab.json` templates ("Move a deal more than one stage forward
  in the CRM"), since BehaviorGPT reads the name. Ids are generic: no account slugs (a test checks
  this).
- **Two tag changes:**
  - `jdrive.open` is keyed by `kind` + `sensitivity`, so reading a call transcript differs from
    reading a price list;
  - `jmail.label` has no tag, because its values are free text.
- Excluded: `ui.*`, `session.*`, `sentinel.*`, and searches (searches are `search` steps, not
  items). `target` (matches_source/other_deal) stays in `ctx` for the rules, not in ids.
- **139 rows.** The SDK caps `complete()` at 100 items, so the BehaviorGPT ranker ranks in chunks
  with `filters={"id": chunk}` and merges the scores (`monitor/catalog.id_chunks`).
- The catalog is refreshed on Unbox under the same name, `actions`, which keeps
  `cat_7c9916ba8e6b222d1084c033` and the slot (`scripts/catalog_sync.py push --keywords`).

## Consequences

- Adding an action or tag value means editing `action_tags.json` and `vocab.json`, then
  regenerating. A test fails if the workspace emits an id that isn't in the catalog.
- The approved runs, rankings cache and calibration are rebuilt for the new ids.
