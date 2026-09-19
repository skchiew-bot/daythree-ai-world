"""Allocates/releases apartment rooms for governed agents (ADR-009). Deterministic:
a returning agent gets back whatever room the DB says it has, never a recomputed
guess — `packages/common/rooms.py` only picks a *new* slot when one doesn't exist
yet.

`ensure_assignment` is exception-contained by design (see its docstring): a bug or
transient DB issue here must never take down agent registration or activation,
which is why routes/agents.py can call it unconditionally with no surrounding
try/except of its own.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import AgentRoomAssignment
from common.rooms import lowest_free_slot, room_to_slot, slot_to_room
from contracts.ids import EntityId, new_id

logger = logging.getLogger(__name__)

# Every concurrent racer initially computes the SAME "lowest free slot" against an
# empty/stale occupied set (they haven't seen each other's commits yet), so under
# heavy contention many collide on the same slot before converging — a losing
# session's retry only needs to out-wait the *other* racers immediately ahead of it,
# but in the worst realistic case that's bounded by how many callers are racing at
# once. 5 was too low even for 8 concurrent registrations in testing (two callers hit
# exhaustion); this is comfortably above any registration burst Phase 0's admin UI can
# realistically produce, and each attempt is a cheap local index check, not a remote
# call, so a higher ceiling costs little.
_MAX_ALLOCATION_ATTEMPTS = 16


async def get_assignment(
    session: AsyncSession, tenant_id: EntityId, agent_id: EntityId
) -> AgentRoomAssignment | None:
    result = await session.execute(
        select(AgentRoomAssignment).where(
            AgentRoomAssignment.tenant_id == tenant_id,
            AgentRoomAssignment.agent_id == agent_id,
            AgentRoomAssignment.released_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def list_assignments(session: AsyncSession, tenant_id: EntityId) -> list[AgentRoomAssignment]:
    result = await session.execute(
        select(AgentRoomAssignment).where(
            AgentRoomAssignment.tenant_id == tenant_id,
            AgentRoomAssignment.released_at.is_(None),
        )
    )
    return list(result.scalars().all())


async def ensure_assignment(
    session: AsyncSession, tenant_id: EntityId, agent_id: EntityId
) -> AgentRoomAssignment | None:
    """Idempotent: returns the agent's existing active room if it has one, otherwise
    allocates the lowest free slot for the tenant. Concurrent callers racing for the
    same slot collide on the partial unique index (`uq_agent_room_assignments_active_room`)
    rather than double-booking; a collision is caught and retried against a
    freshly-recomputed occupancy set, up to `_MAX_ALLOCATION_ATTEMPTS`.

    Never raises: any failure (allocation exhaustion, an unexpected DB error) is
    logged and swallowed, returning None, because room assignment is a presentation
    concern that must never block agent registration or activation.
    """
    try:
        for _ in range(_MAX_ALLOCATION_ATTEMPTS):
            # Re-checked on every attempt, not once up front: a collision can mean a
            # concurrent caller just gave this very agent a room, and retrying into a
            # different slot would then violate the one-active-room-per-agent index.
            existing = await get_assignment(session, tenant_id, agent_id)
            if existing is not None:
                return existing

            occupied = {
                room_to_slot(a.floor, a.room_index)
                for a in await list_assignments(session, tenant_id)
            }
            floor, room_index = slot_to_room(lowest_free_slot(occupied))

            assignment = AgentRoomAssignment(
                id=new_id(), tenant_id=tenant_id, agent_id=agent_id, floor=floor, room_index=room_index,
            )
            session.add(assignment)
            try:
                async with session.begin_nested():
                    await session.flush()
                return assignment
            except IntegrityError:
                # begin_nested()'s __aexit__ issues the SQL-level ROLLBACK TO
                # SAVEPOINT, but against asyncpg that alone leaves the ORM Session's
                # own bookkeeping in a "pending rollback" state — the next execute()
                # on this session raises PendingRollbackError instead of running.
                # An explicit rollback() (safe to call — it's a no-op past what the
                # savepoint already undid) is what actually clears that state so the
                # retry loop's next list_assignments() call can proceed. Found via a
                # concurrency test racing 8 real allocations against a real
                # testcontainers Postgres — no unit test catches this since none of
                # them exercise an actual SAVEPOINT conflict.
                await session.rollback()
                continue

        logger.warning(
            "room_assignment_exhausted", extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
        )
        return None
    except Exception:
        logger.exception(
            "room_assignment_failed", extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
        )
        return None


async def release_assignment(session: AsyncSession, tenant_id: EntityId, agent_id: EntityId) -> None:
    """Frees the agent's active room (if any) so it can be reused. Exception-contained
    for the same reason as `ensure_assignment` — releasing a room must never block
    suspending an agent.
    """
    try:
        assignment = await get_assignment(session, tenant_id, agent_id)
        if assignment is None:
            return
        assignment.released_at = datetime.now(timezone.utc)
        await session.flush()
    except Exception:
        logger.exception(
            "room_release_failed", extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
        )
