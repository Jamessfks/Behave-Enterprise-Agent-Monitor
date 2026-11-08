# 0002. ShiftPoint is the only world; NovaDesk retired

- **Status:** Accepted, 2026-11-08

## Context

main's world (NovaDesk selling seats to Acme Industries) was a handful of hard-coded sources in
`env/scenario.py`. sales-env's world (ShiftPoint, per-location shift scheduling) has a company
bible, 12 accounts, 8 call transcripts, 44 email threads, 30 docs, a CRM and a calendar. It also
contains the same "after the sales call" demo (Acme Foods: call says 5 depots, RFP says 12 +
25%, lookalike account, invented close date, stage jump).

## Decision

ShiftPoint is the only world. Removed from the code:
- `env/scenario.py`, `env/app.py`, `env/company.py`
- the NovaDesk runs (`runs/careful_*.jsonl`, `runs/faulty.jsonl`) and
  `scripts/make_scripted_runs.py`
- main's "Marco" unwritten rules

They stay in git history. The company context the monitor and live agent need is **loaded from
`world/`** (company bible, rules JSON, accounts), not written in Python.

## Consequences

- Adding a company or account means adding files under `world/` and rebuilding the seed
  (`scripts/build_seed.py`), not editing Python.
- Name clash removed: in ShiftPoint, Marco Rossi is the onboarding manager. Unwritten rules come
  from Liam O'Connor (`world/rules/unwritten_rules.json`).
- The step model's approved runs, calibration and the BehaviorGPT catalog are rebuilt for the
  new action space (ADR 0007).

## Alternatives considered

- **Both worlds, switchable.** More flexible, but two catalogs and two sets of approved runs to
  keep calibrated. Rejected by the owner.
