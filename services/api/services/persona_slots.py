"""Atomic persona-slot claiming and first-sight persona creation (ADR-010 B4, T1-F14).

A slot in `agent_runtime_persona_slots` is claimed BEFORE the persona's `agents` row is
inserted, so two concurrent first-sights of two DIFFERENT personas can never both slip
under the 25-slot cap -- the unique index on `(tenant_id, slot)` is the actual guarantee,
not a count-then-insert check (the same discipline as `api.services.room_assignment`). A
second concurrent first-sight of the SAME persona collides on the OTHER unique index
(`tenant_id, agent_code`) instead, and is resolved by re-selecting the row the winner just
created rather than treated as cap exhaustion.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import Agent, AgentRuntimePersonaSlot, AgentVersion, ModelPolicy
from common.hashing import sha256_hex
from contracts.enums import AgentLifecycleState
from contracts.ids import EntityId, new_id

from api.persona_registry import PERSONA_SLOT_CAP, PersonaDefinition

_MAX_CLAIM_ATTEMPTS = PERSONA_SLOT_CAP + 1

CLAUDE_CODE_EXTERNAL_MODEL_POLICY_NAME = "claude-code-external"
PERSONA_CAP_EXCEEDED_DETAIL = "persona_slot_cap_exceeded"


async def _occupied_slots(session: AsyncSession, tenant_id: EntityId) -> set[int]:
    result = await session.execute(
        select(AgentRuntimePersonaSlot.slot).where(AgentRuntimePersonaSlot.tenant_id == tenant_id)
    )
    return {row[0] for row in result.all()}


async def _get_agent_by_code(session: AsyncSession, tenant_id: EntityId, agent_code: str) -> Agent | None:
    result = await session.execute(
        select(Agent).where(Agent.tenant_id == tenant_id, Agent.agent_code == agent_code)
    )
    return result.scalar_one_or_none()


async def resolve_claude_code_external_policy(session: AsyncSession, tenant_id: EntityId) -> ModelPolicy:
    """READ-ONLY resolution by `(tenant_id, name)` -- this route never creates a
    `ModelPolicy` (T1-F11 / build-plan condition C7). Absent is a 409 telling the
    operator to run the seed/issue script rather than silently creating one."""
    result = await session.execute(
        select(ModelPolicy).where(
            ModelPolicy.tenant_id == tenant_id, ModelPolicy.name == CLAUDE_CODE_EXTERNAL_MODEL_POLICY_NAME
        )
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "No 'claude-code-external' model policy exists for this tenant yet -- run "
                "infrastructure/scripts/seed.py before registering Claude Code personas."
            ),
        )
    return policy


async def _claim_slot(session: AsyncSession, tenant_id: EntityId, agent_code: str) -> Agent | None:
    """Returns None once a slot for `agent_code` is durably claimed by THIS call, or
    the pre-existing `Agent` row if a concurrent caller already created this exact
    persona while we were racing. Raises 409 once every slot is occupied."""
    occupied = await _occupied_slots(session, tenant_id)
    for _ in range(_MAX_CLAIM_ATTEMPTS):
        free_slots = [s for s in range(PERSONA_SLOT_CAP) if s not in occupied]
        if not free_slots:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PERSONA_CAP_EXCEEDED_DETAIL)

        slot_row = AgentRuntimePersonaSlot(
            id=new_id(), tenant_id=tenant_id, slot=free_slots[0], agent_code=agent_code
        )
        session.add(slot_row)
        try:
            async with session.begin_nested():
                await session.flush()
            return None
        except IntegrityError:
            # asyncpg gotcha (T1-F12, mirroring room_assignment.py lines ~97-109): the
            # savepoint rollback from begin_nested()'s own __aexit__ leaves the ORM
            # session's bookkeeping in a "pending rollback" state against asyncpg --
            # an explicit session-level rollback() is what actually clears it.
            await session.rollback()
            existing = await _get_agent_by_code(session, tenant_id, agent_code)
            if existing is not None:
                return existing
            occupied = await _occupied_slots(session, tenant_id)
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=PERSONA_CAP_EXCEEDED_DETAIL)


async def ensure_persona(
    session: AsyncSession, *, tenant_id: EntityId, persona: PersonaDefinition, created_by: EntityId | None
) -> Agent:
    """Idempotent on `agent_code`: returns the existing persona `agents` row if this
    tenant already saw it, otherwise claims a slot and creates it `active`, with
    `AgentVersion.runtime_adapter="external_manual"` set explicitly -- the schema
    default is `"custom_durable"`, which would make every task of this persona
    permanently unclosable through complete-external/fail-external (build-plan
    condition C7). A suspended persona is never reactivated here; the caller checks
    `lifecycle_state` on the returned row and 409s."""
    existing = await _get_agent_by_code(session, tenant_id, persona.agent_code)
    if existing is not None:
        return existing

    model_policy = await resolve_claude_code_external_policy(session, tenant_id)

    winner = await _claim_slot(session, tenant_id, persona.agent_code)
    if winner is not None:
        return winner

    agent = Agent(
        id=new_id(), tenant_id=tenant_id, agent_code=persona.agent_code, display_name=persona.display_name,
        description=f"Claude Code subagent persona: {persona.display_name}.",
        lifecycle_state=AgentLifecycleState.active.value, created_by=created_by,
    )
    session.add(agent)
    await session.flush()

    version_payload = {
        "agent_code": persona.agent_code, "runtime_adapter": "external_manual",
        "autonomy_level": persona.autonomy_level.value, "tool_policy": persona.tool_policy.model_dump(),
    }
    version = AgentVersion(
        id=new_id(), agent_id=agent.id, version=1,
        system_prompt=f"Claude Code subagent persona: {persona.display_name}.",
        runtime_adapter="external_manual", model_policy_id=model_policy.id,
        autonomy_level=persona.autonomy_level.value, tool_policy=persona.tool_policy.model_dump(),
        memory_policy={}, settings={}, checksum=sha256_hex(str(version_payload)), created_by=created_by,
    )
    session.add(version)
    await session.flush()

    agent.active_version_id = version.id
    await session.flush()
    await session.refresh(agent)
    return agent
