# Decisions

Each entry says what was chosen and why. Newest first.

## 2026-11-08: BehaviorGPT stays as evidence

- **Decision (you):** BehaviorGPT doesn't get a vote. The company-workflow model decides pauses;
  BehaviorGPT ranks every step live and the UI labels that rank "as evidence".
- **Why:** `scripts/audit_behaviorgpt.py` (91 live calls, `results/behaviorgpt_audit.json`)
  showed the calls are real (about 0.3 s each, also from the Vercel deploy). It also showed that
  with BehaviorGPT switched off the default verdicts are identical, and that as the decider it
  would let "send the quote" through (#2 of 60).
- **Enforced by:** `test_default_verdicts_do_not_depend_on_behaviorgpt`.
- **Fixed along the way:** an empty `RankingCache` counted as false, so `BehaviorGPTRanker` fell
  back to the committed cache. The cache had also drifted from live output (true-step rank
  shift: median 0, max 2), so it was rebuilt from 157 live calls.

## 2026-11-08: MVP build (docs/prompts/build-mvp.md)

### The step model: BehaviorGPT didn't pass go/no-go on its own

- `results/go_no_go.json`: on the six careful runs, BehaviorGPT ranks the true next action at a
  **median of #21 of 60** (top-5 only 13% of the time; random is about #30; re-measured live 2026-11-08, see `results/behaviorgpt_audit.json`). With a task-describing
  `Search` prefix it gets slightly better (#17), but it also ranks the faulty run's steps *better*.
  It rates "send the quote to the client" as the **#2** most likely step after applying a discount,
  which makes sense for a consumer model (view → buy). So it misses mistake 1.
- The SDK has no fine-tuning (that answers the PDF's open question 1). So check 1 can use one of
  three rankers behind one interface (`monitor/rankers.py`, `monitor/normal.py`):
  - **workflow** (default): dependencies learned from the approved runs. The share of good runs
    in which b came before a. A skip is charged once, where it happened. "Always directly
    before" pairs (ask → read the reply) are hard dependencies and never excused.
  - **behaviorgpt**: zero-shot.
  - **blend**: workflow log-score + β × standardized BehaviorGPT score (β fitted on held-out runs).
- Calibration is leave-one-out on the careful runs (`monitor/calibrate.py` →
  `monitor/calibration.json`). Results on the faulty run:

  | Ranker | Caught (of 2 behavior mistakes) | False alarms |
  |---|---|---|
  | workflow | 2 | 0 |
  | blend | 1 | 1 |
  | behaviorgpt | 0 | 0 |

  The default is chosen by that table, not tuned to make the demo fire. The UI shows BehaviorGPT's
  own rank and top guesses on every step whichever ranker decides, and the step-model selector
  lets judges switch.
- Changes from Unbox's method, each written in the code: an exact softmax (small catalog); the
  scale floored at 1 nat (few, near-deterministic runs make the MAD tiny); irreversible actions get
  a per-step gate at u ≥ 3 on top of the CUSUM, because CUSUM deliberately doesn't stop on one
  surprising step.

### Fact check and rules check

- Facts must appear in a source the agent **opened earlier in the run**. The span is returned as
  evidence. A value contradicting the call transcript (the primary source) is flagged unless the
  conflict was resolved with the rep. The amount is derived (seats × price × 12 × (1 − discount)).
- Rules come from the company context: `max_discount_on_send`, `requires_before`
  (incl. `previous_stage`), `forbid`, `advisory`, and `precedent`. **Allow requires a reason**, and
  it becomes a precedent rule. A later step with the same action and failed checks is allowed and
  cites the reason.

### Stateless server, Vercel

- The user asked for Vercel. Vercel functions don't keep in-memory sessions, so the server is
  **stateless**: the browser holds each run and posts `{history, event, context, cusum, ranker}`
  to `/api/check`. Live mode sends the whole agent loop state to `/api/agent/step` and makes at
  most one Claude call per request.
- BehaviorGPT rankings are cached in `runs/rankings_cache.json` (committed), so replay shows
  BehaviorGPT's real ranks with no key. On a read-only file system the cache stays in memory.
- `web/` is mounted last with `StaticFiles`, so Vercel promotes it to the CDN, and API routes win.

### Live mode: app tools, not pixels

- The spec says the app records semantic steps, with no screenshots or vision. Live agents
  (`claude-opus-5-5`) use tools (`list_items`, `open_item`, `crm_update_deal`, `quote`,
  `chat_send`, `calendar_book`, `email`, …) that map one-to-one to catalog actions
  (`env/app.py`). Each call is checked **before** it executes. Computer use stays possible later
  by putting the same app behind a browser.
- Not verified against the real API yet: there's no `ANTHROPIC_API_KEY` in this environment.
  `tests/test_server.py` runs the loop with a fake Claude.

### Company context and catalog upload

- The setup drawer edits the company name, background and unwritten rules. Unwritten rules
  added in the UI are `advisory` (shown to people, not code-checked). Turning free text into
  checkable rules would need an LLM, which is left for later.
- Catalog upload validates a CSV and, on request, embeds it with BehaviorGPT, then previews
  BehaviorGPT's next-action guesses. The demo scenario keeps using the Acme catalog
  (`cat_7c99…`, in `.env` as `UNBOXAI_CATALOG_ID`).

### Facts about the Unbox account

- The SDK's default catalog name `retail_catalog` doesn't exist for this key. Public catalogs are
  `retail_catalog_500k`, `amazon_sample`, `hm_fashion`, `art_catalog` and `PixelRec200K`.
- Measured latency of one ranking call: 0.15–0.4 s.

## 2026-11-08: Phase 0

The original Phase 0 choices (Hugging Face Spaces, Claude computer use, the Northwind workflow)
were replaced by the entries above. The event schema (search/view, no order type,
`details.irreversible`) still holds, extended in docs/event-schema.md.

## Open questions

- Does BehaviorGPT do better on a catalog written as action + outcome ("Send the quote *after
  approval*")? Worth one more go/no-go run.
- More approved runs (recorded from careful live agents) would make the workflow model and the
  barrier less fragile. Six scripted runs are a thin base, and the pitch should say so.
- Mistake 3's other variant (200 seats) is caught by the fact check in tests but isn't in the
  recorded faulty run, so the faulty run pauses exactly three times as the spec asks.
