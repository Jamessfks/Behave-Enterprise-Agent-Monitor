# 0003. Workspace state behind a StateStore: memory locally, Upstash Redis on Vercel

- **Status:** Accepted, 2026-11-08

## Context

The workspace keeps all state in module globals (`store.DATA`, `events.RUN`, `EVENTS`,
`PENDING`, `UNDO`) and wrote it to disk in four places (state file, run logs, learned rules, seed
copy). Vercel runs short-lived instances with a read-only disk, and two requests can land on
different instances. The owner chose to keep Vercel and add a Redis store.

## Decision

- **No disk writes.**
  - `store.save()` and `events._log()` only set `store.CHANGED`.
  - `store.reset()` reads the seed into memory.
  - Learned rules live in `events.LEARNED`.
- **One JSON snapshot** (`events.snapshot()` / `events.restore()`) holds the data, run, run state,
  events, pending approvals, undo snapshots, learned rules and the id counter. `restore()` updates
  the module dicts in place, because templates hold references to them.
- **`workspace/state.py`** defines a `StateStore` with two backends:
  - `MemoryStore` (default): process memory is the state.
  - `RedisStore` (chosen automatically when `UPSTASH_REDIS_REST_*` or `KV_REST_API_*` exist):
    the snapshot is zlib-compressed and base64-encoded under one key, with a version counter.
    Each request takes a lock (`SET NX PX`), reloads only if the version changed, and saves only
    if `CHANGED`.
- **`workspace/session.py`** middleware wraps every stateful request (`/api/*` and the app pages)
  in a store session. It also records who's acting and what request is being made (ADR 0005).
- **Pending approvals store the request, not a closure.** Approving replays that request
  (ADR 0005), so a pause created on one instance can be approved on another.

## Consequences

- The same code runs locally, in tests (memory) and on Vercel (Redis).
- The compressed snapshot is well under 400 KB (a test checks this; Upstash's limit is about
  1 MB per request).
- Requests are serialized by the lock. That's fine for one presenter. Busy multi-user use would
  need per-collection keys (noted for later).
- Learned rules survive world resets, because `start_run` and reset don't clear them.

## Alternatives considered

- **In-memory only on Vercel:** state can vanish between instances. Rejected for a live demo.
- **A container on a stateful host:** simple, but leaves Vercel. Rejected by the owner.
- **Per-collection keys and object-level patches:** fewer bytes per write, more code. Deferred.
