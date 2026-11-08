# 0012. Each step says what it changed, and the next step is known before it runs

- **Status:** Accepted, 2026-11-08

## Context

The demo moved too fast. A step was checked and the app reloaded, but nothing showed how the app
changed: which field, from what to what, or which email or document appeared. The canvas also
only learned a step's page after the step ran, so it couldn't show the app *before* the change.

## Decision

- **The server diffs the world around each write.** `workspace/changes.py` copies the changeable
  collections before a write (`capture()`) and compares them after it (`diff()`). Each change
  names its app, kind (`created | updated | sent | drafted | deleted`), `what`, the page that
  shows it (`url`), `focus` (CSS selectors) and `fields` (`{label, before, after}`, formatted
  as the apps show them).
- **Runner.** `scenarios/runner.py` puts `changes` on every step view (`[]` for reads, paused,
  blocked and skipped steps) via `call_with_changes()`.
- **Approved replays are diffed too.** `events.approve()` returns `changes` and stores them in
  the `sentinel.approved` event's args. When the run continues, the runner copies them onto the
  paused step.
- **The next step is returned ahead of time.** `start`, `next_step` and `current` return
  `upcoming`: the next step's index, label, kind, page and app. The canvas opens that page first,
  then shows before → check → after.
- **Highlighting.** The templates mark what a change points at (`data-field`, `data-thread-id`,
  `data-doc-id`, `data-event-id`, element ids), so the canvas can highlight the change inside the
  framed app. A change's `focus` covers both pages it can be seen on: the list the step opens and
  the object's own page.
- **Scenario steps may carry:**
  - `look_for`: short strings that appear verbatim on a read step's page, the facts to point at;
  - `before_page`: the page to show before a write whose own `page` depends on its output (a quote
    shows the Offers folder, then the new offer doc).

## Consequences

- The canvas can pace a run: show the app, run the check, then show the highlighted change with
  its before and after values.
- Each write deep-copies seven collections. At the demo's size that cost is small; reads copy nothing.
- `tests/test_changes.py` keeps the changes, focus selectors, `upcoming` and `look_for` strings
  honest against the real pages.

## Alternatives

- **Diff from the write's event** (`object`, `args`): misses side effects beyond the object the
  event names (e.g. the email a quote approval request sends) and has no before values.
- **Let the canvas diff page HTML:** fragile, and it can't name fields or format values.
