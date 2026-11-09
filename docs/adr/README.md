# Architecture decision records

One file per decision: `NNNN-short-title.md`, with Status, Context, Decision, Consequences and
Alternatives. A decision that changes later gets a new ADR that supersedes the old one. Don't
edit the old one's text.

| # | Decision | Status |
|---|---|---|
| [0001](0001-merge-sales-env-into-one-codebase.md) | Merge sales-env into one codebase and one app | Accepted |
| [0002](0002-shiftpoint-is-the-only-world.md) | ShiftPoint is the only world; NovaDesk retired | Accepted |
| [0003](0003-state-store-memory-and-upstash.md) | Workspace state behind a StateStore: memory locally, Upstash Redis on Vercel | Accepted |
| [0004](0004-behaviorgpt-is-evidence.md) | BehaviorGPT is evidence, not a decider | Accepted |
| [0005](0005-in-process-monitor-gate.md) | The monitor runs in-process at the workspace's single write gate | Accepted |
| [0006](0006-one-event-contract.md) | One event contract: the workspace event, adapted for the checks | Accepted |
| [0007](0007-catalog-from-tagged-actions.md) | The BehaviorGPT catalog is generated from tagged workspace actions | Accepted |
| [0008](0008-rules-as-data.md) | Rules are data: a few generic kinds cover written, unwritten and learned rules | Accepted |
| [0009](0009-scenarios-execute-against-the-workspace.md) | Demo runs execute against the real workspace, step by step | Accepted |
| [0010](0010-one-agent-with-a-mistakes-switch.md) | One agent with a "Plant mistakes" switch | Accepted |
| [0011](0011-canvas-ui.md) | Split-screen canvas: live app plus a pannable workflow | Accepted |
| [0012](0012-step-changes-and-paced-playback.md) | Each step says what it changed; the next step is known before it runs | Accepted |
| [0013](0013-live-computer-use-and-warm-behaviorgpt.md) | Live mode drives the apps by computer use; BehaviorGPT, warm-started, judges it (supersedes 0004 for Live) | Accepted |
