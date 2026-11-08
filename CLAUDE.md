# Sentinel (sudai2)

Hackathon project: a behavioral oversight layer for computer-use agents doing sales workflows.
The full brief, architecture, and task list are in [docs/PROJECT.md](docs/PROJECT.md). Read it
before starting work.

- Keep it simple: this is a few-hour demo. Favor replayable, deterministic pieces.
- All three parts share one event format: `step`, `type`, `action_id`, `timestamp`, `details`.
  Don't change it without updating every consumer.
- BehaviorGPT (Unbox AI) is an external API; check its real SDK before writing against it.
