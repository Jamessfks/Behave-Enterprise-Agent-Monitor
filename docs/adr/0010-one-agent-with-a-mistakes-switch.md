# 0010. One agent with a "Plant mistakes" switch

- **Status:** Accepted, 2026-11-08

## Context

The demo had two buttons, "Careful agent" and "Faulty agent". They're the same agent doing the
same task (Acme Foods, after the call); only the mistakes differ. Two agents suggested two
systems and made the demo longer to explain.

## Decision

One **Run the agent** button with a **Plant mistakes** switch, on by default for the demo.
- **Off:** the careful script. It asks Alex about 5 vs 12 depots, quotes 10%, requests Dana's
  approval for 25%, moves Discovery → Demo, leaves the close date, and drafts without sending.
  No pauses.
- **On:** the faulty script, with four planted mistakes: stage jump to Negotiation, close date
  2026-12-31, amount set as if 12 depots at 25%, and the 25% quote sent without approval. Four
  pauses, each caught by a named check.

Both scripts live in `scenarios/acme_after_call.py` and share their steps up to the point where
they diverge. Live mode (a Claude agent on any typed request) stays a separate mode.

## Consequences

- The end screen compares the latest run with and without mistakes when both have been played.
- The four-pause count (not the PDF's three) is deliberate. It matches the teammate's script and
  shows the pilot-scope rule.
