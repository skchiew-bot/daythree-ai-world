from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db.models import Agent, AgentVersion, User
from common.hashing import sha256_hex
from contracts.enums import AgentLifecycleState, EventType, UserRole
from contracts.events import Actor, ActorType, build_event
from contracts.ids import EntityId, new_id

from api.dependencies.auth import get_current_user, get_tenant_scoped_or_404, require_role
from api.dependencies.db import get_db_session
from api.dependencies.events import get_event_publisher
from api.schemas.agents import AgentCreateRequest, AgentResponse, AgentVersionCreateRequest, AgentVersionResponse

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

MUTATORS = require_role(UserRole.platform_admin, UserRole.tenant_admin, UserRole.operator)


async def _publish(publisher, session, event_type, tenant_id, actor, agent_id, data=None):
    event = build_event(
        event_type=event_type, tenant_id=tenant_id, correlation_id=agent_id, actor=actor,
        service="api", agent_id=agent_id, data=data or {},
    )
    await publisher.publish(event, session)


def _version_checksum(payload: AgentVersionCreateRequest) -> str:
    return sha256_hex(payload.model_dump_json())


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreateRequest,
    user: User = Depends(MUTATORS),
    session: AsyncSession = Depends(get_db_session),
    publisher=Depends(get_event_publisher),
) -> Agent:
    agent = Agent(
        id=new_id(), tenant_id=user.tenant_id, agent_code=payload.agent_code,
        display_name=payload.display_name, description=payload.description,
        department=payload.department, role_name=payload.role_name,
        lifecycle_state=AgentLifecycleState.draft.value, created_by=user.id,
    )
    session.add(agent)
    await session.flush()

    version = AgentVersion(
        id=new_id(), agent_id=agent.id, version=1,
        system_prompt=payload.version.system_prompt, runtime_adapter=payload.version.runtime_adapter,
        model_policy_id=payload.version.model_policy_id, autonomy_level=payload.version.autonomy_level.value,
        tool_policy=payload.version.tool_policy.model_dump(), memory_policy=payload.version.memory_policy,
        settings=payload.version.settings, checksum=_version_checksum(payload.version), created_by=user.id,
    )
    session.add(version)
    await session.flush()

    agent.active_version_id = version.id
    agent.lifecycle_state = AgentLifecycleState.active.value
    await session.flush()

    actor = Actor(type=ActorType.user, id=user.id)
    await _publish(publisher, session, EventType.agent_created, user.tenant_id, actor, agent.id)
    await _publish(
        publisher, session, EventType.agent_version_created, user.tenant_id, actor, agent.id,
        data={"version": version.version, "checksum": version.checksum},
    )
    return agent


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> list[Agent]:
    result = await session.execute(select(Agent).where(Agent.tenant_id == user.tenant_id))
    return list(result.scalars().all())


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: EntityId, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_db_session)
) -> Agent:
    agent = await get_tenant_scoped_or_404(session, Agent, agent_id, user.tenant_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return agent


@router.post("/{agent_id}/versions", response_model=AgentVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_agent_version(
    agent_id: EntityId, payload: AgentVersionCreateRequest,
    user: User = Depends(MUTATORS), session: AsyncSession = Depends(get_db_session),
    publisher=Depends(get_event_publisher),
) -> AgentVersion:
    """No in-place editing (spec §8.4): every call creates a brand-new, immutable
    version row. The caller must separately call `/activate` to point `agents.
    active_version_id` at it — creating a version never silently activates it."""
    agent = await get_tenant_scoped_or_404(session, Agent, agent_id, user.tenant_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")

    max_version = (
        await session.execute(select(AgentVersion.version).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version.desc()).limit(1))
    ).scalar_one_or_none() or 0

    version = AgentVersion(
        id=new_id(), agent_id=agent.id, version=max_version + 1,
        system_prompt=payload.system_prompt, runtime_adapter=payload.runtime_adapter,
        model_policy_id=payload.model_policy_id, autonomy_level=payload.autonomy_level.value,
        tool_policy=payload.tool_policy.model_dump(), memory_policy=payload.memory_policy,
        settings=payload.settings, checksum=_version_checksum(payload), created_by=user.id,
    )
    session.add(version)
    await session.flush()

    actor = Actor(type=ActorType.user, id=user.id)
    await _publish(
        publisher, session, EventType.agent_version_created, user.tenant_id, actor, agent.id,
        data={"version": version.version, "checksum": version.checksum},
    )
    return version


@router.post("/{agent_id}/activate", response_model=AgentResponse)
async def activate_agent(
    agent_id: EntityId, version_id: EntityId,
    user: User = Depends(MUTATORS), session: AsyncSession = Depends(get_db_session),
    publisher=Depends(get_event_publisher),
) -> Agent:
    agent = await get_tenant_scoped_or_404(session, Agent, agent_id, user.tenant_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    version = await session.get(AgentVersion, version_id)
    if version is None or version.agent_id != agent.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Version does not belong to this agent.")

    agent.active_version_id = version.id
    agent.lifecycle_state = AgentLifecycleState.active.value
    await session.flush()

    await _publish(
        publisher, session, EventType.agent_activated, user.tenant_id, Actor(type=ActorType.user, id=user.id),
        agent.id, data={"active_version_id": str(version.id)},
    )
    return agent


@router.post("/{agent_id}/suspend", response_model=AgentResponse)
async def suspend_agent(
    agent_id: EntityId, user: User = Depends(MUTATORS), session: AsyncSession = Depends(get_db_session),
    publisher=Depends(get_event_publisher),
) -> Agent:
    agent = await get_tenant_scoped_or_404(session, Agent, agent_id, user.tenant_id)
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")

    agent.lifecycle_state = AgentLifecycleState.suspended.value
    await session.flush()

    await _publish(
        publisher, session, EventType.agent_suspended, user.tenant_id, Actor(type=ActorType.user, id=user.id), agent.id
    )
    return agent
