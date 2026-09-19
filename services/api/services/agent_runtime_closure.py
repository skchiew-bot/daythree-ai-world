"""T2 deliverable 3: the one place a twin Task is ever closed -- by a hook (`/close`),
by SessionEnd, or by the reaper. All three funnel through `close_task` so the
idempotency guarantee (T2-F9), the audit shape (ids and enum values only) and the
never-touch-the-Mission rule live in exactly one function.

Deliberately does NOT import or call anything from `routes/tasks.py` or
`mission_engine/engine/recovery.py` (T2 hard constraint) -- `complete_task_external`/
`fail_task_external` both end the Mission and accept free-text `reason`, and
`recovery.py` is R0's own orphan-sweep bookkeeping, unrelated to this phase.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from common.db.models import (
    Agent,
    AgentRuntimeClosure,
    AgentRuntimeSession,
    AgentVersion,
    Mission,
    Task,
)
from contracts.enums import (
    ActorType,
    AgentRuntimeCloseOutcome,
    AgentRuntimeClosedBy,
    AgentRuntimeKind,
    AgentRuntimeOutcome,
    AgentRuntimeReasonCode,
    EventType,
    MissionStatus,
    TaskStatus,
)
from contracts.events import Actor, build_event
from contracts.ids import EntityId, new_id

from mission_engine.engine.mission_service import mark_mission_status
from mission_engine.states.transitions import InvalidTransition, validate_task_transition

_TERMINAL_TASK_STATUSES = frozenset(
    {TaskStatus.completed.value, TaskStatus.failed.value, TaskStatus.cancelled.value}
)
_RUNTIME_ADAPTER_EXCLUDED = "custom_durable"


async def _get_existing_closure(session: AsyncSession, runtime_session_id: EntityId) -> Optional[AgentRuntimeClosure]:
    return (
        await session.execute(
            select(AgentRuntimeClosure).where(AgentRuntimeClosure.runtime_session_id == runtime_session_id)
        )
    ).scalar_one_or_none()


async def _publish(publisher, session, event_type, tenant_id, actor, mission_id, task_id=None, agent_id=None, data=None):
    event = build_event(
        event_type=event_type, tenant_id=tenant_id, correlation_id=mission_id, actor=actor, service="api",
        mission_id=mission_id, task_id=task_id, agent_id=agent_id, data=data or {},
    )
    await publisher.publish(event, session)


async def _advance_task(
    session: AsyncSession, publisher, *, tenant_id: EntityId, actor: Actor, mission_id: Optional[EntityId],
    task: Task, target: TaskStatus, reason_code: str,
) -> None:
    """`queued -> running -> target` in one call (mirroring `routes/tasks.py`'s own
    complete/fail-external shape) -- a no-op if `task` is already terminal, so a first
    closure attempt against a Task some other path already finished never raises."""
    if task.status in _TERMINAL_TASK_STATUSES:
        return
    if task.status == TaskStatus.queued.value:
        validate_task_transition(TaskStatus.queued, TaskStatus.running)
        task.status = TaskStatus.running.value
        task.started_at = func.now()
        await _publish(
            publisher, session, EventType.task_started, tenant_id, actor, mission_id,
            task_id=task.id, agent_id=task.assigned_agent_id,
        )
        await session.flush()
    elif task.status == TaskStatus.waiting.value and target == TaskStatus.completed:
        # TASK_TRANSITIONS has no waiting->completed edge (only waiting->{running,
        # failed, cancelled}) -- a twin Task should never actually reach `waiting`
        # (that state belongs to the internal task_executor's model-call flow, not
        # an externally-run twin), but closing it as `completed` must not 500 if it
        # somehow does. `running` is the only legal hop between waiting and
        # completed; the Task already started earlier (whatever put it in
        # `waiting` came after `running`), so no new `task.started` event.
        validate_task_transition(TaskStatus.waiting, TaskStatus.running)
        task.status = TaskStatus.running.value
        await session.flush()

    validate_task_transition(TaskStatus(task.status), target)
    task.status = target.value
    task.completed_at = func.now()
    event_type = EventType.task_completed if target == TaskStatus.completed else EventType.task_failed
    await _publish(
        publisher, session, event_type, tenant_id, actor, mission_id,
        task_id=task.id, agent_id=task.assigned_agent_id, data={"reason_code": reason_code},
    )


async def close_task(
    session: AsyncSession,
    publisher,
    *,
    tenant_id: EntityId,
    actor: Actor,
    runtime_session_id: EntityId,
    outcome: AgentRuntimeCloseOutcome,
    reason_code: AgentRuntimeReasonCode,
    closed_by: AgentRuntimeClosedBy,
    tool_call_count: Optional[int],
) -> tuple[Optional[AgentRuntimeClosure], bool]:
    """Closes one subagent's Task and writes its closure row (T2-F5/T2-F9).

    Returns `(closure, is_new)`. `closure` is `None` only when `runtime_session_id`
    does not resolve to a row in this tenant (the caller 404s). `is_new` is False for
    every duplicate/idempotent-replay path, including the late-close case (T2-F1
    deliverable 9): a hook close arriving after the reaper already closed the same
    row is a 200 that leaves the Task `failed` and stamps `late_close_at` on the
    EXISTING closure row rather than creating a second one.

    `SELECT ... FOR UPDATE` on the runtime-session row is taken FIRST and serializes
    every closer of this row across transactions -- by the time the lock is held, no
    other transaction can be racing to insert a closure for the same
    `runtime_session_id`, so the existing-closure check just below is race-free in the
    ordinary case and a genuinely new closure can be inserted directly. This
    deliberately differs from `routes/agent_runtime.py`'s own IntegrityError-then-
    `session.rollback()` pattern (T1-F12) for the EXPECTED path: THIS function is
    called in a loop by `end_session` and `reap_stale_runtime_sessions`, both of which
    must complete several closes inside one shared transaction -- a full
    `session.rollback()` for one duplicate would discard every sibling close already
    done in that same transaction. The UNIQUE(runtime_session_id) constraint is still
    a REAL backstop, not just a schema-level comment: the insert below runs inside its
    own `begin_nested()` savepoint, so if the constraint ever does fire (this function
    called with a stale lock, a bug elsewhere), only that savepoint rolls back --
    mirroring `services/api/services/room_assignment.py`'s own asyncpg-safe pattern --
    and the caller gets the existing row back instead of a poisoned transaction.
    """
    stmt = (
        select(AgentRuntimeSession)
        .where(AgentRuntimeSession.id == runtime_session_id, AgentRuntimeSession.tenant_id == tenant_id)
        .with_for_update()
    )
    runtime_session = (await session.execute(stmt)).scalar_one_or_none()
    if runtime_session is None:
        return None, False

    existing = await _get_existing_closure(session, runtime_session_id)
    if existing is not None:
        if (
            closed_by == AgentRuntimeClosedBy.hook
            and existing.closed_by == AgentRuntimeClosedBy.reaper.value
            and existing.late_close_at is None
        ):
            existing.late_close_at = func.now()
            await session.flush()
            # Same MissingGreenlet/DetachedInstanceError risk `mission_service.py`'s
            # own CAS updates already document: assigning `func.now()` leaves the
            # attribute needing a reload, which a later sync-context read (or a read
            # after this session closes) cannot perform. Refresh right here, where
            # the row was actually changed, so every caller gets a real value back.
            await session.refresh(existing)
        return existing, False

    task = await session.get(Task, runtime_session.task_id) if runtime_session.task_id else None
    mission_id = runtime_session.mission_id
    target_status = TaskStatus.completed if outcome == AgentRuntimeCloseOutcome.completed else TaskStatus.failed

    closure = AgentRuntimeClosure(
        id=new_id(), tenant_id=tenant_id, runtime_session_id=runtime_session.id,
        task_id=runtime_session.task_id, closed_by=closed_by.value, outcome=outcome.value,
        reason_code=reason_code.value, tool_call_count=tool_call_count, artifact_id=None,
    )
    try:
        async with session.begin_nested():
            session.add(closure)
            await session.flush()
    except IntegrityError:
        # The savepoint rollback from `begin_nested()`'s own `__aexit__` is scoped to
        # just this INSERT -- unlike `routes/agent_runtime.py`'s full-session
        # rollback, it leaves every earlier statement in THIS transaction (a sibling
        # close in the same `end_session`/reaper loop) intact and the session fully
        # usable for the re-read right below.
        existing = await _get_existing_closure(session, runtime_session_id)
        if existing is None:
            raise
        return existing, False

    if task is not None:
        await _advance_task(
            session, publisher, tenant_id=tenant_id, actor=actor, mission_id=mission_id,
            task=task, target=target_status, reason_code=reason_code.value,
        )

    runtime_session.ended_at = func.now()
    runtime_session.outcome = outcome.value
    await session.flush()

    return closure, True


async def end_session(
    session: AsyncSession,
    publisher,
    *,
    tenant_id: EntityId,
    actor: Actor,
    runtime_session_id: EntityId,
    outcome: AgentRuntimeOutcome,
) -> Optional[AgentRuntimeSession]:
    """T2-F7: ends a `kind='session'` runtime session in one transaction -- its parent
    Task `queued|running -> completed`, every still-open subagent Task `failed` with
    `closed_by=session_end`, then the Mission `running -> completed`. Idempotent: a
    session whose `ended_at` is already set is returned unchanged (T2-F6, deliverable
    6's "a session's end state is set once")."""
    stmt = (
        select(AgentRuntimeSession)
        .where(AgentRuntimeSession.id == runtime_session_id, AgentRuntimeSession.tenant_id == tenant_id)
        .with_for_update()
    )
    runtime_session = (await session.execute(stmt)).scalar_one_or_none()
    if runtime_session is None:
        return None
    if runtime_session.ended_at is not None:
        return runtime_session

    parent_task = await session.get(Task, runtime_session.task_id) if runtime_session.task_id else None
    if parent_task is not None:
        await _advance_task(
            session, publisher, tenant_id=tenant_id, actor=actor, mission_id=runtime_session.mission_id,
            task=parent_task, target=TaskStatus.completed, reason_code=AgentRuntimeReasonCode.session_ended.value,
        )

    open_subagents = (
        await session.execute(
            select(AgentRuntimeSession.id).where(
                AgentRuntimeSession.parent_session_id == runtime_session.id,
                AgentRuntimeSession.ended_at.is_(None),
            )
        )
    ).scalars().all()
    for sub_id in open_subagents:
        await close_task(
            session, publisher, tenant_id=tenant_id, actor=actor, runtime_session_id=sub_id,
            outcome=AgentRuntimeCloseOutcome.failed, reason_code=AgentRuntimeReasonCode.session_ended,
            closed_by=AgentRuntimeClosedBy.session_end, tool_call_count=None,
        )

    if runtime_session.mission_id is not None:
        mission = await session.get(Mission, runtime_session.mission_id)
        if mission is not None and mission.status == MissionStatus.running.value:
            try:
                await mark_mission_status(session, mission, MissionStatus.completed)
            except InvalidTransition:
                pass  # defensive only -- running->completed is always legal (transitions.py)

    runtime_session.ended_at = func.now()
    runtime_session.outcome = outcome.value
    await session.flush()
    return runtime_session


def _stale_subagents_query(cutoff: datetime, batch_size: int):
    parent = aliased(AgentRuntimeSession)
    return (
        select(AgentRuntimeSession.id, AgentRuntimeSession.tenant_id, AgentRuntimeSession.parent_session_id)
        .join(parent, parent.id == AgentRuntimeSession.parent_session_id)
        .join(Task, Task.id == AgentRuntimeSession.task_id)
        .join(Agent, Agent.id == Task.assigned_agent_id)
        .join(AgentVersion, AgentVersion.id == Agent.active_version_id)
        .where(
            AgentRuntimeSession.kind == AgentRuntimeKind.subagent.value,
            AgentRuntimeSession.ended_at.is_(None),
            AgentVersion.runtime_adapter != _RUNTIME_ADAPTER_EXCLUDED,
            func.greatest(
                func.coalesce(AgentRuntimeSession.last_heartbeat_at, AgentRuntimeSession.started_at),
                parent.last_heartbeat_at,
                parent.started_at,
            )
            < cutoff,
        )
        .limit(batch_size)
        .with_for_update(of=AgentRuntimeSession, skip_locked=True)
    )


def _stale_sessions_query(cutoff: datetime, batch_size: int):
    open_subagent = aliased(AgentRuntimeSession)
    still_has_open_subagents = (
        select(open_subagent.id)
        .where(open_subagent.parent_session_id == AgentRuntimeSession.id, open_subagent.ended_at.is_(None))
        .exists()
    )
    return (
        select(AgentRuntimeSession.id, AgentRuntimeSession.tenant_id)
        .join(Task, Task.id == AgentRuntimeSession.task_id)
        .join(Agent, Agent.id == Task.assigned_agent_id)
        .join(AgentVersion, AgentVersion.id == Agent.active_version_id)
        .where(
            AgentRuntimeSession.kind == AgentRuntimeKind.session.value,
            AgentRuntimeSession.ended_at.is_(None),
            AgentVersion.runtime_adapter != _RUNTIME_ADAPTER_EXCLUDED,
            func.coalesce(AgentRuntimeSession.last_heartbeat_at, AgentRuntimeSession.started_at) < cutoff,
            ~still_has_open_subagents,
        )
        .limit(batch_size)
        .with_for_update(of=AgentRuntimeSession, skip_locked=True)
    )


async def reap_stale_runtime_sessions(
    session: AsyncSession, publisher, *, reap_window: timedelta, now: Optional[datetime] = None, batch_size: int = 200
) -> int:
    """T2-F1/D30: reaps subagents whose own AND parent's last activity are both older
    than `reap_window`, then ends every session whose subagents are all closed and
    whose own last activity is also stale (deliverable 8's "when every subagent of a
    silent session is closed and the parent is also stale"). `FOR UPDATE SKIP LOCKED`
    is what makes two concurrent reaper sweeps reap each row exactly once -- restartable,
    no resident state, safe to call from the worker loop on a plain timer.

    Never touches a `custom_durable` task (the explicit `runtime_adapter` guard in the
    query) and joins only through `agent_runtime_sessions`, mirroring the guard
    `worker.main.requeue_orphaned_running_tasks` already applies to its own sweep.

    Returns the number of subagents newly reaped (informational, mirrors R0's own
    `requeued` count in the worker log line).
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - reap_window
    actor = Actor(type=ActorType.system)

    reaped = 0
    for runtime_session_id, tenant_id, _parent_id in (
        await session.execute(_stale_subagents_query(cutoff, batch_size))
    ).all():
        _closure, is_new = await close_task(
            session, publisher, tenant_id=tenant_id, actor=actor, runtime_session_id=runtime_session_id,
            outcome=AgentRuntimeCloseOutcome.failed, reason_code=AgentRuntimeReasonCode.reaped_stale,
            closed_by=AgentRuntimeClosedBy.reaper, tool_call_count=None,
        )
        if is_new:
            reaped += 1

    for runtime_session_id, tenant_id in (
        await session.execute(_stale_sessions_query(cutoff, batch_size))
    ).all():
        await end_session(
            session, publisher, tenant_id=tenant_id, actor=actor, runtime_session_id=runtime_session_id,
            outcome=AgentRuntimeOutcome.abandoned,
        )

    return reaped


@dataclass(frozen=True)
class HookLossRate:
    since: datetime
    until: datetime
    lost: int
    total: int
    rate: float


async def compute_hook_loss_rate(
    session: AsyncSession, tenant_id: EntityId, *, since: datetime, until: Optional[datetime] = None
) -> HookLossRate:
    """T2 deliverable 10: computed on read, no stored counter. Lost means
    `closed_by='reaper' AND late_close_at IS NULL` (a late-closing hook removes a row
    from the numerator without changing the denominator), over ALL subagent closures
    in `[since, until)` -- every row in this table already is a subagent closure,
    since `close_task` is never called for anything else."""
    until = until or datetime.now(timezone.utc)
    total = (
        await session.execute(
            select(func.count()).select_from(AgentRuntimeClosure).where(
                AgentRuntimeClosure.tenant_id == tenant_id,
                AgentRuntimeClosure.closed_at >= since,
                AgentRuntimeClosure.closed_at < until,
            )
        )
    ).scalar_one()
    lost = (
        await session.execute(
            select(func.count()).select_from(AgentRuntimeClosure).where(
                AgentRuntimeClosure.tenant_id == tenant_id,
                AgentRuntimeClosure.closed_at >= since,
                AgentRuntimeClosure.closed_at < until,
                AgentRuntimeClosure.closed_by == AgentRuntimeClosedBy.reaper.value,
                AgentRuntimeClosure.late_close_at.is_(None),
            )
        )
    ).scalar_one()
    rate = (lost / total) if total else 0.0
    return HookLossRate(since=since, until=until, lost=lost, total=total, rate=rate)
