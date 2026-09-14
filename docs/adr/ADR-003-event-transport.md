# ADR-003: Event Transport & Task Queue

## Context

Spec §6 lists "Celery / Dramatiq / native async worker" as the three acceptable options
for task execution, and Redis Streams as the event-broadcast transport (spec §5/§9/§15).
Phase 0 has exactly one task per mission and a single-tenant local deployment target
(spec §26) — the concurrency and durability needs are modest.

## Options Considered

1. **Celery** with Redis as broker/backend.
2. **Dramatiq** with Redis as broker.
3. **A native asyncio worker** (`services/worker/main.py`) polling a plain Redis list
   (`BRPOP`) for task ids, alongside a separate Redis Stream purely for the event
   broadcast (spec §9).

## Decision

Native asyncio worker + a plain Redis list as the task queue + a Redis Stream as the
event broadcast — no Celery, no Dramatiq.

## Rationale

- Celery and Dramatiq are built around synchronous worker processes (or add real
  complexity to run natively async); Phase 0's entire domain layer
  (`mission_engine`, `agent_runtime`, `model_gateway`) is `async def` end-to-end using
  SQLAlchemy's async engine — bridging that into a sync task-runner would mean either
  blocking the event loop per task or running a sync-to-async shim for no real benefit
  at Phase 0's single-task-per-mission scale.
- A plain Redis list (`LPUSH`/`BRPOP`) gives exactly the "at-least-once, single consumer
  wins" delivery Phase 0 needs; the actual durability guarantee (a task is never lost)
  comes from the **database** row (`tasks.status`), not from the queue — the queue is
  just a wakeup signal. `worker/main.py`'s startup scan for orphaned `running` tasks is
  what actually implements "survive a crash," independent of whatever was or wasn't
  still in the Redis list when the process died.
- Fewer moving parts (no Celery result backend, no Flower, no broker-specific retry
  policy layered on top of the domain-level retry policy already in
  `policy_sdk.budgets`) means fewer places for spec §4 rule 15 ("no silent fallback") to
  be silently violated by a queue library's own defaults.

## Consequences

- **The Redis client used for `BRPOP` must be constructed with `socket_timeout=None`.**
  redis-py applies its own client-side socket read timeout independently of a blocking
  command's own `timeout` argument; whichever is shorter wins, and a default/finite
  socket_timeout races BRPOP's server-side block and raises `redis.exceptions.
  TimeoutError` on nearly every poll. Combined with `docker-compose.yml`'s `restart:
  unless-stopped` on the worker (added for an unrelated startup-ordering race), this
  crash-looped the worker container indefinitely — found by CI's E2E job, whose
  longer sustained-polling runtime exposed it in a way the resilience suite's one-shot
  `docker compose kill worker` never would have. Fixed in `services/worker/deps.py::
  build_redis_client`.
- No built-in task scheduling/cron, priority queues, or multi-queue routing — none of
  which Phase 0 needs (one task type, one queue).
- Horizontal scaling of the worker (multiple replicas) works today (Redis `BRPOP` is
  safe for multiple consumers), but there is no per-task lease/visibility-timeout
  mechanism the way Celery/SQS provide — a worker that hangs (not crashes) mid-task
  holds that task until it's manually restarted. Acceptable at Phase 0 scale; a real
  lease mechanism is a reasonable Phase 1 addition if worker hangs (as opposed to
  crashes) become a real operational issue.

## Rollback Path

Swap `services/worker/main.py`'s queue loop for a Celery/Dramatiq task registration —
`mission_engine.engine.task_executor.execute_task` is already a plain `async def` that
only needs a task id and a DB session, so it can be called from any task-runner without
changes to the Mission Engine, Agent Runtime, or Model Gateway.
