# Sentinel — project brief

**Working title:** Sentinel, a behavioral oversight layer for autonomous sales agents.

## Overview

AI agents are starting to do knowledge work the way people do. Instead of being wired into each
system through APIs, they operate the computer directly: reading emails, checking internal
documents and updating records. When an agent works across many applications without a human
watching each step, how do you know it's still on track?

Sentinel pairs a computer-use agent with a Large Behavioral Model (BehaviorGPT, from Unbox AI) that
watches every action, judges whether it makes sense in context, and calls in a human the moment the
agent's behavior stops looking right.

## Problem

- Rule-based automation (Zapier etc.) is reliable but rigid. It can't handle open-ended judgment.
- Computer-use agents handle open-ended work, but they fail quietly: a misread email, a record
  updated for the wrong client, a quote sent too early.
- Teams need to supervise agents without a person reviewing every click.

## Architecture (three layers)

1. **Simulated work environment.** Inbox, internal documents, call transcripts and a CRM database,
   all in one web app we control. The workflow has two phases: gather information, then act on it.
2. **Computer-use agent.** A general-purpose agent (for example Claude computer use) that is told
   to carry out the workflow as an employee would.
3. **Monitor.** Each agent action is translated into a structured event from a fixed **action
   catalog**. At every step BehaviorGPT reads the full history and ranks the catalog by how likely
   each action is to come next. Sentinel compares that ranking with what the agent actually did.

Event sources: either the environment app emits semantic events, or we map the computer-use API's
own action logs (click, type, select) onto catalog IDs. The environment events are the fallback if
the agent logs prove too low-level.

## Detection logic

- Don't stop on one surprising step: real workflows have several valid orderings.
- Per step: rank of the actual action → surprise → add to a running **risk score** for the session.
- The threshold is calibrated on known-good runs.
- When the score crosses the threshold: pause the agent, notify the user, and list the actions that
  triggered the alert. The user can **Approve** (resume) or **Stop**.
- As steps are confirmed, the history grows and the model gets more context.

## Why a behavioral model

Language models judge actions by how they're described. A behavioral model judges them by how they
fit a sequence of real actions. BehaviorGPT can rank catalogs it hasn't seen without training, so a
new workflow only needs a well-described action catalog and no labeled failures.

## Demo scope

- One end-to-end sales workflow running live, deployed online.
- Dashboard: live action feed, risk score chart with threshold line, workflow progress.
- An alert card with Approve and Stop controls.
- A deliberately injected mistake that the system catches in real time.
- Replay mode, so the demo doesn't depend on the live agent.

## Open question

Does a model pretrained on consumer behavior transfer to office workflows? The go/no-go test below
measures this directly. Fallback: a simple transition model fitted on scripted runs.

---

# To-do

Owners: **P1** = Environment & Agent, **P2** = Monitor, **P3** = UI.

## Phase 0: Align (everyone, ~20 min)

- [x] Pick ONE sales workflow and write its correct steps → [workflow.md](workflow.md)
- [x] Agree on the shared event format: `step`, `type` (search / view), `action_id`,
      `timestamp`, `details` → [event-schema.md](event-schema.md)
- [x] Choose the stack, deploy target, and computer-use agent → [decisions.md](decisions.md)
- [x] Confirm `pip install behaviorgpt` works (v0.10.0, `uv sync`)
- [ ] Get the Unbox API key (portal.unboxai.com) into your local `.env`: **needs a team member**

## Phase 1: Build in parallel

### Environment & Agent (P1)
- [ ] Fake inbox, document store and CRM as one simple web app
- [ ] Seed data: lead emails (one with an attachment), internal docs, call transcripts, CRM records
- [ ] Every action in the app emits a semantic event mapped to a catalog ID
- [ ] Scripted "email arrives in 5 minutes" trigger
- [ ] Record 3–5 correct runs and 1 run with a deliberate mistake (calibration + demo replay)
- [ ] Connect the computer-use agent and write its task prompt
- [ ] Pause/resume so the agent waits for approval when flagged

### Monitor (P2)
- [ ] Action catalog CSV (~30–60 actions, including plausible wrong ones): name, brand (app name),
      categories, image, price
- [ ] Upload with `catalog_from_csv` and `client.embed`
- [ ] **Go/no-go test (first hour):** feed the correct workflow one prefix at a time; check where the
      true next action ranks
- [ ] If ranks are poor: fallback transition model fitted on the scripted runs
- [ ] Scoring loop: rank the actual action, convert rank to surprise, add to running risk score
- [ ] Set the threshold on clean runs; confirm the mistake run crosses it
- [ ] Expose risk score, alert, and the flagged actions to the UI

### UI (P3)
- [ ] Dashboard: live action feed, risk chart with threshold line, workflow progress
- [ ] Alert card listing flagged actions, with Approve and Stop
- [ ] In-app notification (email/Slack optional)
- [ ] Live updates from the backend
- [ ] Replay mode for recorded runs

## Phase 2: Integrate (everyone)

- [ ] End to end: agent → environment events → monitor → UI
- [ ] Inject the mistake; confirm the alert fires and names the right actions
- [ ] Approve resumes the agent; Stop halts it
- [ ] Deploy online and test from another device

## Phase 3: Demo prep

- [ ] Backup video of a full run, including the alert
- [ ] Final description and short pitch: problem → demo → why a behavioral model
- [ ] One slide with go/no-go results ("does it transfer to office work?")
- [ ] Rehearse; decide who presents what

## If time runs short, cut in this order

1. Email/Slack notifications (keep the in-app alert)
2. Checking actions before they execute
3. Running the live agent during the demo (use replay mode)
