# 0008. Rules are data: a few generic kinds cover written, unwritten and learned rules

- **Status:** Accepted, 2026-11-08

## Context

main's rules check had special-purpose kinds (`max_discount_on_send`, `forbid`, …) and a rule
author ("Marco") from the retired NovaDesk world. ShiftPoint's rules are JSON in
`world/rules/written_rules.json` and `unwritten_rules.json` (author Liam O'Connor), and people
add rules every time they Allow or Block with a reason.

## Decision

- **Four generic kinds** (`monitor/rules.py`):
  - **`match`**: `{when, unless, severity: pause|block}`. A small predicate language over a view
    of the step: dotted paths like `ctx.crm_change`, `offer.discount_pct`, `company.id`; equals,
    in-list, `gt/ge/lt/le` against numbers or `@facts.name`, `glob`, `not`.
  - **`requires_before`**: a step needs an earlier one.
  - **`advisory`**: shown to people, not checked by code.
  - **`precedent`**: a learned Allow.
- **Every rule in `world/rules/*.json` carries a machine-readable `spec`**; their text, author and
  source stay for display. Examples:
  - over-15% sends need Dana's approval;
  - over 25% is blocked;
  - stage skips pause;
  - do-not-contact, confidential to external, and note overwrites are blocked;
  - Liam: Acme at most 10% before procurement, and quote the pilot scope.
- **Agent-role rules** in `world/company/context.json`:
  - out-of-scope records (a read is a flag);
  - writes to a deal other than the transcript's;
  - agent D never writes;
  - no agent approves its own quote.
- **Learned rules** (`events.LEARNED`, kept in the snapshot, surviving resets):
  - a learned Allow is a precedent for the same catalog action and company that covers the
    checks it failed;
  - a learned Block becomes a block rule naming the person.
- **Company facts** (seller domain, per-location prices, discount limits, stages, location nouns)
  live in `world/company/context.json`, not in Python. Main's Marco rules are removed.

## Consequences

- A new company or rule means editing JSON, not code. A test validates every spec.
- Two judgment calls, both kept, written down in the code and tested:
  - next-step dates aren't fact-checked (the bible only requires amount and close date to come
    from the customer);
  - a pilot can be just the rollout order (Ironclad: "pilot at five sites… license all thirty").
