# 0013. Live mode drives the apps by computer use; BehaviorGPT, warm-started, judges it

- **Status:** Accepted, 2026-11-08. Supersedes ADR 0004 for Live computer-use runs only; the
  demo task keeps BehaviorGPT as evidence.

## Context

Live mode needed `ANTHROPIC_API_KEY` and called the workspace's JSON routes as tools, so it was
off in this environment and never showed an agent using the apps the way the product pitches it:
on screen, like a person. BehaviorGPT, shown on every step as evidence, ranked the true next step
poorly cold: median rank 86 of 139 on the approved runs (worse than random), 0% in its top 5.

## Decision

- **Computer use.** With `GEMINI_API_KEY` set (and not on Vercel), `POST /api/runs` with an
  `instruction` starts `agent/computer_use.py`: it resets the world, starts a run, and launches
  `computer_use/gemini_agent.py` as a child process. That opens a visible Edge window on the
  ShiftPoint apps, sends `X-Actor: agent` on every request, and lets Gemini act on screenshots
  with click / type / scroll / press_key / wait / finish. The Claude tool agent stays the fallback
  when only `ANTHROPIC_API_KEY` is set.
- **One gate, unchanged.** Because the browser identifies as the agent, every page it opens is
  logged and scored and every form it submits passes `events.commit()` (ADR 0005). A paused write
  shows the blue "Paused by Sentinel" banner on the agent's screen and a pause card on the canvas.
- **The canvas follows the run.** `POST /api/runs/current/next` waits up to 20 s for the agent's
  next meaningful event (not `ui.*`, `session.*`) and returns it as a step view; `working: true`
  means "still working, ask again". The agent reports its summary on
  `POST /api/runs/current/finish`. A new run of any kind stops the agent.
- **Plain functions, not Google's computer-use tool.** Measured on Gemini 3.5 Flash-Lite with the
  same screenshot: ~0.9-2 s per turn with declared functions, ~10 s median (2.5-29 s, occasional
  90 s stalls) with the built-in tool. Coordinates stay 0-999. Thinking is MINIMAL for Flash-Lite
  and LOW for 3.8 Flash (it rejects MINIMAL). After each action the agent is told when nothing on
  screen changed and when the page is scrolled down (Flash-Lite otherwise keeps clicking tabs it
  scrolled off screen).
- **Warm-start BehaviorGPT, in Live mode only.** For computer-use runs the gate asks
  `core.bgpt_live()`: before the run in progress it sends `BGPT_WARM_START` approved runs
  (default 3) as earlier sessions, chosen about the same account as the run (its most frequent
  entity so far), then others. It uses `LIVE_UNBOXAI_CATALOG_ID` (else `UNBOXAI_CATALOG_ID`)
  and its own cache (`.untracked/live_rankings_cache.json`). A run is never among its own
  examples. The demo task is untouched: cold ranker, team catalog, committed cache.
- **BehaviorGPT judges Live changes.** `workspace_gate._behaviorgpt_judge`: a write ranked
  outside BehaviorGPT's top `LIVE_BGPT_CUTOFF` (default 8) fails a `behaviorgpt` check and
  pauses. While such a step waits, `GET /api/runs/current/agent` reports `halted`; the agent
  process stops acting and covers its window with a red notice; the canvas pops up an alert.
  Allow (with a reason, which becomes a rule as usual) lets the agent continue; Block ends the
  run and the agent. Reads are never judged: the approved runs contain no browsing.
- **Why these numbers.** Rank of what was really done next, on the company's runs:

  | BehaviorGPT | Correct changes (86 writes, 24 approved runs) | 5 planted mistakes (eval run) |
  |---|---|---|
  | Cold | median 86 over all steps (6 runs) | |
  | Warm, first 3 approved runs | median 55, up to 118 | 5-62: ranked *more* expected |
  | Warm, same account | median 3, p90 52 | 4, 10, 14, 17, 20 |

  With same-account examples, cutoff top 8 catches 4 of 5 mistakes (stage jump, invented close
  date, quote for the wrong amount, quote sent before approval; not the amount change) and holds
  22 of 86 correct changes (9 of 24 careful runs stopped at least once). Top 5: same catches, 26
  held. Top 10: 3 caught. Samples are small: one eval run.
- **Clock fix (loaded with the Live ranker).** `monitor/clockfix.py` shifts the SDK's clock back 60 s: on a PC whose clock runs
  a few seconds fast, the SDK stamps history events in the future and the API silently drops them
  (rankings then ignore the history; measured).

## Consequences

- Live mode is local only (it needs a browser on the machine) and costs Gemini calls; the key's
  quota shows up as 429s that the agent retries.
- Approved runs come from the scripted runner, which calls routes directly, so they contain no
  browsing steps (`jdrive.open_folder`, list pages). A computer-use agent's browsing looks unusual
  to the step model and to BehaviorGPT. Recording approved runs with a careful computer-use agent
  would fix that.
- On Windows the workspace needed two portability fixes: `workspace/timefmt.py` (`%-d` is POSIX
  only) and running Python in UTF-8 mode (`PYTHONUTF8=1`) so world files read correctly.

## Alternatives

- Google's built-in computer-use tool: kept the model's trained action format but was 5-10x
  slower per turn on this key, with stalls. The Interactions API also blocked every follow-up turn
  as a "safety violation" with this key, even on a blank page.
- Claude computer use: no Anthropic key in this environment.
