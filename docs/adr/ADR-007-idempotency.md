# ADR-007: Idempotency

## Context

Spec §14 requires idempotent mission start, task start, artifact creation, model retry,
and event publication, with the explicit failure scenario: "if worker crashes after
artifact storage but before final task update, retry must detect the existing artifact
and reconcile instead of creating an uncontrolled duplicate" (also TC-P0-007, TC-P0-010).

## Options Considered

1. **Database-enforced idempotency**: unique constraints as the actual guarantee,
   application-level "check first" as an optimization/UX layer on top, with a
   `SAVEPOINT`-scoped reconciliation path when the check-first optimization loses a race.
2. A separate `idempotency_keys` ledger table recording every operation attempted, with
   the application responsible for looking it up before doing anything.
3. Rely on the application layer alone (check-then-act) with no DB-level constraint,
   accepting an occasional duplicate under concurrent retries.

## Decision

Option 1, applied at three points:

- **Mission start**: `UPDATE missions SET status='running' ... WHERE status IN
  ('draft','ready') RETURNING id` — an atomic compare-and-swap, not a separate
  check-then-update (`mission_engine/engine/mission_service.py::start_mission`).
- **Task creation**: `tasks.idempotency_key` is `UNIQUE`; the one task per mission uses
  the deterministic key `f"{mission_id}:task:1"`, so re-deriving it after a retry finds
  the same row instead of computing a new one.
- **Artifact commit**: `uq_artifacts_idempotent_commit` on `(task_id, artifact_type,
  logical_output_slot, version)`, exactly as spec §14 specifies; the insert runs inside
  a `SAVEPOINT` (`session.begin_nested()`) so a conflict rolls back only that insert, not
  the caller's whole transaction (`artifact_service/service.py::commit_artifact`).

## Rationale

- A separate idempotency-keys ledger (option 2) duplicates information the domain tables
  already carry (a task's own id/status IS its idempotency record) and adds a place for
  the ledger and the real state to drift out of sync under a crash.
- Application-only check-then-act (option 3) has an unavoidable TOCTOU race under
  concurrent retries — exactly the scenario spec §15/§27 test explicitly ("Duplicate
  Start Request... Expected: only one run", TC-P0-010) is designed to catch.
- Layering an app-level "check first" read *in front of* the DB constraint (rather than
  relying on the constraint alone) is a deliberate two-layer design: the fast path (no
  contention) never even attempts a doomed insert or throws an exception for control
  flow; the constraint is the actual safety net for the race, not the primary mechanism.

## Consequences

- **`start_mission` never enqueues to Redis itself — the caller must commit its
  transaction first, then enqueue.** The first version had `start_mission` both insert
  the task row *and* push it to Redis before returning. Once the worker's two earlier
  startup bugs were fixed (see ADR-001/ADR-003) and it could reliably win the `BRPOP`
  race within milliseconds of a task being queued, it started consistently beating the
  producer's own `session.commit()` — the worker would `session.get(Task, task_id)` on
  its own connection and find nothing, because the INSERT was still only visible
  inside the producer's uncommitted transaction. `TaskExecutionError: Task ... does not
  exist`, deterministically, on a healthy fast worker. This is the classic dual-write
  ordering hazard, and the fix is the standard one: commit the state change before
  publishing that it happened, not after. Both call sites
  (`services/api/routes/missions.py`, `infrastructure/scripts/run_demo_mission.py`)
  now do `await session.commit()` then `await enqueue_task(...)` explicitly, and
  `start_mission`'s own docstring states this contract for any future caller.
- Every idempotent operation needs a deterministic key computed the same way on every
  attempt (`f"{mission_id}:task:1"` for the one Phase 0 task, `logical_output_slot="primary"`
  for the one Phase 0 output) — a design that assumes "one task per mission, one output
  per task" and needs a real slot-naming scheme if Phase 1+ introduces multiple tasks or
  multiple named outputs per mission.
- `SAVEPOINT` support is Postgres-specific (see ADR-002) — another reason SQLite was
  never substituted for tests.

## Rollback Path

None anticipated — this is a correctness mechanism, not a swappable component. If a
future phase needs idempotency across a wider action set, extend the same pattern
(deterministic key + unique constraint + savepoint-scoped reconciliation) rather than
introducing a parallel ledger-based mechanism.
