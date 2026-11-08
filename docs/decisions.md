# Decisions

**Status: Phase 0, 2026-11-08.** Each entry says what was chosen and why. Revisit an entry only
with a reason, and update it here when you do.

## Stack: one Python app

- **Backend:** Python 3.12 + FastAPI, managed with `uv` (`pyproject.toml`). The BehaviorGPT SDK is
  Python, and Unbox's anomaly app, which we adapt, is FastAPI. One process serves all three parts.
- **Fake environment (Inbox, Docs, Transcripts, CRM, Email):** server-rendered pages plus plain
  HTML/JS under `env/`, with no build step. Each user action posts an event to `/api/events`.
  Data is seeded from JSON in `env/seed/`. State is in memory and resets per run.
- **Monitor:** `monitor/`, with an async `AsyncUnboxAIClient` and an on-disk ranking cache
  (SQLite in `.untracked/`).
- **Dashboard UI:** plain HTML/CSS/JS under `web/` (same pattern as upstream), with live updates
  over Server-Sent Events and a small chart lib from a CDN. No React build. Saves time and nothing
  to break at deploy.
- **Python ≥ 3.11** is required by the SDK. The repo pins 3.12.

Layout:

```
env/        fake workplace app + seed data
monitor/    scoring, calibration, go/no-go
agent/      computer-use loop + task prompt
web/        dashboard
catalog/    actions.csv (source of truth)
runs/       recorded and scripted runs (*.jsonl)
server.py   FastAPI entry point mounting all of the above
```

## Deployment: one Docker container

- One `Dockerfile` running `uvicorn server:app` on `$PORT`. The same image runs locally and online.
- **Host: Hugging Face Spaces (Docker SDK)**, the way upstream deploys its anomaly demo. It's free,
  gives a public https URL, keeps one long-lived process (in-memory run state and SSE work), and
  takes secrets in the Space settings. Fallback: Render or Fly.io (same image).
- Not Vercel for v1: functions are serverless instances, so in-memory run state and the SSE
  stream would need an external store. That's doable, but not worth it in a few hours.
- **Replay mode** works without any API key (pre-scored runs ship in `runs/`), so the public URL
  demos even if keys or quotas fail.

## Computer-use agent: Claude

- **Model:** `claude-opus-5-5` with tool `{"type": "computer_toolset_20260801"}`. This needs no
  beta header (see `docs/reference/computer-use.md`).
- **Where it runs:** Anthropic's reference container
  ([computer-use-demo](https://github.com/anthropics/claude-quickstarts/tree/main/computer-use-demo)),
  locally in Docker, with its Firefox opened on the environment URL. The agent never sees real
  accounts or credentials.
- **Events come from the environment**, not from the agent's click log. The agent's tool calls are
  shown in the dashboard as a side panel only.
- **Pausing:** the environment gates irreversible actions via `/api/runs/{id}/gate`. The agent
  loop also checks `flagged` between iterations and waits for Approve/Stop.

## Monitor fallback

If the go/no-go test fails, swap `BehaviorGPTRanker` for `TransitionRanker` (first-order counts from
the scripted runs). Same interface, so the UI and agent don't change. See the `monitor-scoring` skill.

## Secrets

`.env` (gitignored; template in `.env.example`): `UNBOXAI_API_KEY`, `UNBOXAI_CATALOG_ID`,
`ANTHROPIC_API_KEY`. On the host, the same names are set as Space secrets.

## Open / owner needed

- [ ] **Unbox API key:** a team member signs in at portal.unboxai.com and puts the key in their
      local `.env`. Not in chat, not in git.
- [ ] **Anthropic API key** with computer-use access, for the agent.
- [ ] **Hugging Face account/org** to own the Space.
- [x] `pip install behaviorgpt` works: v0.10.0 installed with `uv sync` on Python 3.12; imports
      and the client raise `AuthenticationError` without a key, as expected.
