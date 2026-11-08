# 0004. BehaviorGPT is evidence, not a decider

- **Status:** Accepted, 2026-11-08 (decided before the merge; restated for the merged app)

## Context

On main's workflow, BehaviorGPT ranked the true next step at a median of #21 of 60 and rated
"send the quote" as the #2 most likely step (`results/behaviorgpt_audit.json`). The SDK has no
fine-tuning. A step model learned from the company's approved runs caught every planted
behavior mistake with no false alarms.

## Decision

- The company-workflow ranker decides when a step is unusual.
- BehaviorGPT ranks every step live (or from the committed cache), and its rank and top guesses
  are shown as evidence.
- A test proves verdicts don't change when BehaviorGPT is down.
- The merged world gets a new catalog (ADR 0007), so the go/no-go test and calibration are
  re-run on it. The numbers are reported, not assumed.

## Consequences

- The demo works without an Unbox key. BehaviorGPT outages never block an agent.
- If BehaviorGPT does better on the new catalog, a later ADR can give it a vote. The ranker
  interface already supports that (`blend`, `behaviorgpt`).
