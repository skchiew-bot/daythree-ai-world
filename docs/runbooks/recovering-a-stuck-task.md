# Runbook: A Task Is Stuck in `running`

## Symptom

A task's status stays `running` far longer than expected, and its mission never
reaches `completed`/`failed`.

## Likely cause

The worker process that owned the task died (crash, OOM kill, manual `docker compose
kill worker`) after marking the task `running` but before it reached a terminal state.

## Fix

1. Confirm the worker is actually down or was restarted:
   ```bash
   docker compose ps worker
   docker compose logs worker --tail=100
   ```
2. Restart the worker if it isn't already running:
   ```bash
   docker compose up -d worker
   ```
   On startup, the worker automatically re-queues every task still in `running`
   status (`worker/main.py::requeue_orphaned_running_tasks`) — no manual DB edit
   needed. It will resume from the task's last `runtime_checkpoints` row rather than
   re-running the whole task from scratch (see `docs/adr/ADR-004-agent-runtime-adapter.md`).
3. Watch the mission's timeline for a `runtime.recovered` event confirming the resume:
   ```bash
   curl -s -H "Authorization: Bearer $TOKEN" \
     http://localhost:8000/api/v1/missions/$MISSION_ID/timeline | jq
   ```
4. If the task is *still* stuck after a worker restart (no `runtime.recovered` event
   appears within a minute), the worker process itself may not be starting cleanly —
   check `docker compose logs worker` for a startup exception before assuming the task
   itself is the problem.

## If it never recovers

As a last resort, an operator can force a clean retry via the API rather than editing
the database directly:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/tasks/$TASK_ID/retry
```

This only succeeds if the task is currently in a state `retry` is valid from (see
`mission_engine/states/transitions.py::TASK_TRANSITIONS`) — a `running` task must first
be confirmed genuinely orphaned (worker actually dead, not just slow) before forcing
this, since forcing a retry on a task a live worker is still legitimately processing
would race with that worker.
