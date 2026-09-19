"""`POST`/`PATCH /api/v1/agent-runtime/sessions` (ADR-010 Phase A, T1 deliverable 4)
plus the T2 close routes (`POST .../subagents/{ref}/close`, `POST .../sessions/{id}/close`).

Registers a Claude Code session or subagent spawn as governed objects under the scoped
`agent_runtime` credential (`api.dependencies.agent_runtime_auth`). Every other router in
`routes/__init__.py` refuses this credential outright (T1-F3) -- this file is the only
place it can write anything.

Deliberately does NOT touch `services/api/services/room_assignment.py::ensure_assignment`
(T1-F6): that helper's own `IntegrityError` branch calls `session.rollback()`, which would
discard this whole registration; the world read already backfills rooms lazily. It also
never calls `tasks.py`'s `complete-external`/`fail-external` (T2-F5): both end the Mission
and accept a free-text `reason` -- lifecycle CLOSURE goes through
`api.services.agent_runtime_closure` instead, which never touches the Mission on the
close path and never stores free text.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import Agent, AgentRuntimeClosure, AgentRuntimeSession, Task, User
from contracts.enums import (
    AgentLifecycleState,
    AgentRuntimeClosedBy,
    AgentRuntimeKind,
    EventType,
    MissionStatus,
    TaskStatus,
)
from contracts.events import Actor, ActorType, build_event
from contracts.ids import EntityId, new_id
from contracts.policy import BudgetPolicy

from api.dependencies.agent_runtime_auth import AgentRuntimePrincipal, get_agent_runtime_principal
from api.dependencies.db import get_db_session
from api.dependencies.events import get_event_publisher
from api.dependencies.redis_client import get_redis_client
from api.persona_registry import resolve_persona
from api.schemas.agent_runtime import (
    AgentRuntimeCloseRequest,
    AgentRuntimeClosureResponse,
    AgentRuntimeSessionCreateRequest,
    AgentRuntimeSessionResponse,
    AgentRuntimeSessionUpdateRequest,
)
from api.services.agent_runtime_closure import close_task, end_session
from api.services.persona_slots import ensure_persona

from mission_engine.engine.mission_service import create_mission, mark_mission_status, start_mission

router = APIRouter(prefix="/api/v1/agent-runtime", tags=["agent-runtime"])

# Same fixed-window pattern as external_agents.py/projects.py, keyed per tenant AND per
# key id (not just per user) so a rotated-but-not-yet-revoked second key gets its own
# budget rather than starving the first. Sized generously for the T3 heartbeat cadence
# (a hook fires at most once per tool call, well under one per second).
_RATE_LIMIT_MAX_REQUESTS = 60
_RATE_LIMIT_WINDOW_SECONDS = 60


async def _enforce_rate_limit(redis: Redis, tenant_id: EntityId, key_id: EntityId, route: str) -> None:
    key = f"ratelimit:agent-runtime:{route}:{tenant_id}:{key_id}"
    count = await redis.incr(key)
    await redis.expire(key, _RATE_LIMIT_WINDOW_SECONDS, nx=True)
    if count > _RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many agent-runtime calls; slow down and retry shortly.",
        )


async def _publish(publisher, session, event_type, tenant_id, actor, mission_id, task_id=None, agent_id=None):
    event = build_event(
        event_type=event_type, tenant_id=tenant_id, correlation_id=mission_id, actor=actor, service="api",
        mission_id=mission_id, task_id=task_id, agent_id=agent_id,
    )
    await publisher.publish(event, session)


async def _get_agent_by_code(session: AsyncSession, tenant_id: EntityId, agent_code: str) -> Agent | None:
    result = await session.execute(
        select(Agent).where(Agent.tenant_id == tenant_id, Agent.agent_code == agent_code)
    )
    return result.scalar_one_or_none()


async def _get_runtime_session(
    session: AsyncSession, tenant_id: EntityId, *, kind: str,
    external_session_ref: str | None = None, external_instance_ref: str | None = None,
) -> AgentRuntimeSession | None:
    stmt = select(AgentRuntimeSession).where(
        AgentRuntimeSession.tenant_id == tenant_id, AgentRuntimeSession.kind == kind
    )
    if external_session_ref is not None:
        stmt = stmt.where(AgentRuntimeSession.external_session_ref == external_session_ref)
    if external_instance_ref is not None:
        stmt = stmt.where(AgentRuntimeSession.external_instance_ref == external_instance_ref)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _register_session(
    session: AsyncSession, publisher, user: User, payload: AgentRuntimeSessionCreateRequest
) -> AgentRuntimeSession:
    tenant_id = user.tenant_id
    existing = await _get_runtime_session(
        session, tenant_id, kind=AgentRuntimeKind.session.value, external_session_ref=payload.external_session_ref
    )
    if existing is not None:
        return existing

    claude_code = await _get_agent_by_code(session, tenant_id, "AGT-CLAUDE-CODE")
    if claude_code is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="AGT-CLAUDE-CODE is not seeded for this tenant -- run infrastructure/scripts/seed.py first.",
        )
    claude_code_id = claude_code.id

    try:
        async with session.begin_nested():
            mission = await create_mission(
                session, tenant_id=tenant_id, mission_code=payload.external_session_ref,
                title=f"Claude Code session {payload.external_session_ref}",
                objective="Claude Code session.", requested_by=user.id, assigned_agent_id=claude_code_id,
                budget_policy=BudgetPolicy(),
            )
            # draft -> ready -> running (build-plan deliverable 4: transitions.py
            # forbids draft -> running directly): mark_mission_status validates the
            # first hop; start_mission's own atomic CAS then completes the second and
            # creates the mission's one Task, mirroring routes/missions.py's own
            # start flow (but never enqueued to Redis -- AGT-CLAUDE-CODE is
            # external_manual, and only routes/missions.py's caller decides to
            # enqueue for custom_durable agents).
            await mark_mission_status(session, mission, MissionStatus.ready)
            start_result = await start_mission(session, mission_id=mission.id)

            runtime_session = AgentRuntimeSession(
                id=new_id(), tenant_id=tenant_id, kind=AgentRuntimeKind.session.value, agent_id=claude_code_id,
                mission_id=mission.id, task_id=start_result.task.id,
                external_session_ref=payload.external_session_ref,
            )
            session.add(runtime_session)
            await session.flush()
    except IntegrityError:
        # T1-F12 (asyncpg gotcha, mirroring room_assignment.py lines ~97-109):
        # begin_nested()'s savepoint rollback alone leaves the ORM session's own
        # bookkeeping in a "pending rollback" state -- an explicit session.rollback()
        # is what actually clears it, at the cost of discarding this whole attempt
        # (never continue mid-transaction after it).
        await session.rollback()
        existing = await _get_runtime_session(
            session, tenant_id, kind=AgentRuntimeKind.session.value,
            external_session_ref=payload.external_session_ref,
        )
        if existing is None:
            raise
        return existing

    actor = Actor(type=ActorType.user, id=user.id)
    mission_id = mission.id
    task_id = start_result.task.id
    task_agent_id = start_result.task.assigned_agent_id
    await _publish(publisher, session, EventType.mission_created, tenant_id, actor, mission_id, agent_id=claude_code_id)
    await _publish(publisher, session, EventType.mission_started, tenant_id, actor, mission_id, agent_id=claude_code_id)
    await _publish(publisher, session, EventType.task_created, tenant_id, actor, mission_id, task_id=task_id, agent_id=task_agent_id)
    await _publish(publisher, session, EventType.task_assigned, tenant_id, actor, mission_id, task_id=task_id, agent_id=task_agent_id)

    return runtime_session


async def _register_subagent(
    session: AsyncSession, publisher, user: User, payload: AgentRuntimeSessionCreateRequest
) -> AgentRuntimeSession:
    tenant_id = user.tenant_id
    existing = await _get_runtime_session(
        session, tenant_id, kind=AgentRuntimeKind.subagent.value,
        external_instance_ref=payload.external_instance_ref,
    )
    if existing is not None:
        return existing

    parent = await _get_runtime_session(
        session, tenant_id, kind=AgentRuntimeKind.session.value,
        external_session_ref=payload.parent_external_session_ref,
    )
    if parent is None or parent.mission_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parent session is not registered.")
    # T3-F2 (operator-approved): a NEW subagent under a session that already ended would
    # create a Task under a completed Mission, which the reaper then counts as a lost
    # hook. Refused before any write (no persona row, no Task). The idempotent-replay
    # early return above is deliberately untouched, so a retried registration of a ref
    # that already exists still returns its stored row.
    if parent.ended_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="parent_session_ended")
    parent_id = parent.id
    parent_mission_id = parent.mission_id

    persona_def = resolve_persona(payload.agent_type)
    persona_agent = await ensure_persona(session, tenant_id=tenant_id, persona=persona_def, created_by=user.id)
    if persona_agent.lifecycle_state == AgentLifecycleState.suspended.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This persona is suspended.")
    persona_agent_id = persona_agent.id
    persona_display_name = persona_agent.display_name

    idempotency_key = f"{parent_mission_id}:ar:{payload.external_instance_ref}"

    try:
        async with session.begin_nested():
            task = Task(
                id=new_id(), mission_id=parent_mission_id, assigned_agent_id=persona_agent_id,
                title=f"{persona_display_name} ({payload.external_instance_ref})",
                instructions="Claude Code subagent spawn; see agent_runtime_sessions for correlation.",
                status=TaskStatus.queued.value, idempotency_key=idempotency_key,
                budget_policy=BudgetPolicy().model_dump(), input_context={},
            )
            session.add(task)
            await session.flush()

            runtime_session = AgentRuntimeSession(
                id=new_id(), tenant_id=tenant_id, kind=AgentRuntimeKind.subagent.value, agent_id=persona_agent_id,
                mission_id=parent_mission_id, task_id=task.id,
                external_session_ref=payload.parent_external_session_ref,
                external_instance_ref=payload.external_instance_ref, parent_session_id=parent_id,
            )
            session.add(runtime_session)
            await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await _get_runtime_session(
            session, tenant_id, kind=AgentRuntimeKind.subagent.value,
            external_instance_ref=payload.external_instance_ref,
        )
        if existing is None:
            raise
        return existing

    actor = Actor(type=ActorType.user, id=user.id)
    task_id = task.id
    await _publish(publisher, session, EventType.task_created, tenant_id, actor, parent_mission_id, task_id=task_id, agent_id=persona_agent_id)
    await _publish(publisher, session, EventType.task_assigned, tenant_id, actor, parent_mission_id, task_id=task_id, agent_id=persona_agent_id)

    return runtime_session


@router.post("/sessions", response_model=AgentRuntimeSessionResponse, status_code=status.HTTP_201_CREATED)
async def register_session(
    payload: AgentRuntimeSessionCreateRequest,
    principal: AgentRuntimePrincipal = Depends(get_agent_runtime_principal),
    session: AsyncSession = Depends(get_db_session),
    publisher=Depends(get_event_publisher),
    redis_client: Redis = Depends(get_redis_client),
) -> AgentRuntimeSession:
    await _enforce_rate_limit(redis_client, principal.user.tenant_id, principal.key_id, "sessions")

    if payload.kind == AgentRuntimeKind.session:
        return await _register_session(session, publisher, principal.user, payload)
    return await _register_subagent(session, publisher, principal.user, payload)


@router.patch("/sessions/{session_id}", response_model=AgentRuntimeSessionResponse)
async def update_session(
    session_id: EntityId,
    payload: AgentRuntimeSessionUpdateRequest,
    principal: AgentRuntimePrincipal = Depends(get_agent_runtime_principal),
    session: AsyncSession = Depends(get_db_session),
    publisher=Depends(get_event_publisher),
    redis_client: Redis = Depends(get_redis_client),
) -> AgentRuntimeSession:
    """Heartbeat (`outcome` absent), or SessionEnd (`outcome` present on a
    `kind='session'` row -- T2-F7). A `kind='subagent'` row with an `outcome` is 409
    (T2-F6: "use /close" instead); this is a 404, not a 403, on a cross-tenant id
    (TC-P0-012 discipline: a tenant-scoped lookup that can't even reveal existence to
    the wrong tenant)."""
    await _enforce_rate_limit(redis_client, principal.user.tenant_id, principal.key_id, "sessions-heartbeat")

    result = await session.execute(
        select(AgentRuntimeSession).where(
            AgentRuntimeSession.id == session_id, AgentRuntimeSession.tenant_id == principal.user.tenant_id
        )
    )
    runtime_session = result.scalar_one_or_none()
    if runtime_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime session not found.")

    if payload.outcome is None:
        runtime_session.last_heartbeat_at = datetime.now(timezone.utc)
        await session.flush()
        return runtime_session

    if runtime_session.kind == AgentRuntimeKind.subagent.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This is a subagent session; use POST .../subagents/{ref}/close or "
            "POST .../sessions/{id}/close instead.",
        )

    # T2-F6: a session's end state is set once -- `end_session` itself is the
    # idempotency guard (a second SessionEnd, via PATCH or the reaper, changes
    # nothing), so a duplicate PATCH here is a 200 no-op, never a 409.
    actor = Actor(type=ActorType.user, id=principal.user.id)
    await end_session(
        session, publisher, tenant_id=principal.user.tenant_id, actor=actor,
        runtime_session_id=runtime_session.id, outcome=payload.outcome,
    )
    await session.refresh(runtime_session)
    return runtime_session


async def _resolve_subagent_for_close(
    session: AsyncSession, tenant_id: EntityId, *, session_id: EntityId | None, external_instance_ref: str | None
) -> AgentRuntimeSession:
    stmt = select(AgentRuntimeSession).where(AgentRuntimeSession.tenant_id == tenant_id)
    if session_id is not None:
        stmt = stmt.where(AgentRuntimeSession.id == session_id)
    else:
        stmt = stmt.where(AgentRuntimeSession.external_instance_ref == external_instance_ref)
    runtime_session = (await session.execute(stmt)).scalar_one_or_none()
    if runtime_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime session not found.")
    if runtime_session.kind != AgentRuntimeKind.subagent.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This is a session, not a subagent; use PATCH .../sessions/{id} to end it.",
        )
    return runtime_session


async def _close_subagent(
    session: AsyncSession, publisher, principal: AgentRuntimePrincipal, runtime_session: AgentRuntimeSession,
    payload: AgentRuntimeCloseRequest,
) -> AgentRuntimeClosure:
    actor = Actor(type=ActorType.user, id=principal.user.id)
    closure, _is_new = await close_task(
        session, publisher, tenant_id=principal.user.tenant_id, actor=actor,
        runtime_session_id=runtime_session.id, outcome=payload.outcome, reason_code=payload.reason_code,
        closed_by=AgentRuntimeClosedBy.hook, tool_call_count=payload.tool_call_count,
    )
    if closure is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime session not found.")
    return closure


@router.post("/subagents/{external_instance_ref}/close", response_model=AgentRuntimeClosureResponse)
async def close_subagent_by_ref(
    external_instance_ref: str,
    payload: AgentRuntimeCloseRequest,
    principal: AgentRuntimePrincipal = Depends(get_agent_runtime_principal),
    session: AsyncSession = Depends(get_db_session),
    publisher=Depends(get_event_publisher),
    redis_client: Redis = Depends(get_redis_client),
) -> AgentRuntimeClosure:
    """T2 deliverable 2: the stateless T3 hook only knows `external_instance_ref`,
    never the internal runtime-session id -- resolved by tenant plus T1's own partial
    unique index on this column."""
    await _enforce_rate_limit(redis_client, principal.user.tenant_id, principal.key_id, "close")
    runtime_session = await _resolve_subagent_for_close(
        session, principal.user.tenant_id, session_id=None, external_instance_ref=external_instance_ref
    )
    return await _close_subagent(session, publisher, principal, runtime_session, payload)


@router.post("/sessions/{session_id}/close", response_model=AgentRuntimeClosureResponse)
async def close_subagent_by_id(
    session_id: EntityId,
    payload: AgentRuntimeCloseRequest,
    principal: AgentRuntimePrincipal = Depends(get_agent_runtime_principal),
    session: AsyncSession = Depends(get_db_session),
    publisher=Depends(get_event_publisher),
    redis_client: Redis = Depends(get_redis_client),
) -> AgentRuntimeClosure:
    """T2 deliverable 2: the same close handler, addressed by the internal runtime-
    session id instead of the external ref -- cross-tenant or cross-session ids are
    404, same discipline as `update_session` above."""
    await _enforce_rate_limit(redis_client, principal.user.tenant_id, principal.key_id, "close")
    runtime_session = await _resolve_subagent_for_close(
        session, principal.user.tenant_id, session_id=session_id, external_instance_ref=None
    )
    return await _close_subagent(session, publisher, principal, runtime_session, payload)
