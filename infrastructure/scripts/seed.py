"""Seeds exactly what spec §18 (and §2's success criteria) require: one tenant, one
local admin, one model policy, and the one mandatory seed agent (Atlas). Safe to run
more than once — every insert is guarded by a lookup-first check, so re-running after
a partial failure reconciles instead of duplicating.
"""
from __future__ import annotations

import asyncio

import structlog
from sqlalchemy import select

from common.config import get_settings
from common.db.models import Agent, AgentVersion, ModelPolicy, Tenant, User
from common.db.session import get_sessionmaker
from common.hashing import sha256_hex
from contracts.enums import AgentLifecycleState, AutonomyLevel, ToolName, UserRole, UserStatus
from contracts.ids import new_id
from contracts.policy import ToolPolicy

logger = structlog.get_logger(__name__)

ATLAS_SYSTEM_PROMPT = (
    "You are Atlas, a Daythree AI Labs Research Analyst. Your job is to analyze the "
    "assigned requirement using only the information and tools provided. Separate "
    "verified facts, assumptions, risks, and recommendations. Never invent evidence. "
    "If required information is unavailable, clearly identify the gap. Produce a "
    "concise, structured artifact suitable for management review."
)

CLAUDE_CODE_DESCRIPTION = (
    "Runs outside Daythree's process boundary (a Claude Code session) — missions "
    "assigned here are never picked up by the internal worker; the agent itself "
    "reports completion via POST /api/v1/tasks/{id}/complete-external, reusing the "
    "same output validator, artifact storage, and audit trail as an internally-"
    "executed agent. Its tool_policy and budget_policy are NOT runtime-enforced "
    "(Daythree has no visibility into a Claude Code session's real tool calls or "
    "model usage) — advisory documentation only, not governance."
)


async def seed() -> None:
    settings = get_settings()
    sessionmaker = get_sessionmaker()

    async with sessionmaker() as session:
        tenant = (
            await session.execute(select(Tenant).where(Tenant.code == settings.seed_tenant_code))
        ).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(id=new_id(), code=settings.seed_tenant_code, name="Daythree HQ")
            session.add(tenant)
            await session.flush()
            logger.info("seeded_tenant", tenant_id=str(tenant.id))

        admin = (
            await session.execute(
                select(User).where(User.tenant_id == tenant.id, User.email == settings.seed_admin_email)
            )
        ).scalar_one_or_none()
        if admin is None:
            from api.dependencies.auth import hash_password

            admin = User(
                id=new_id(), tenant_id=tenant.id, email=settings.seed_admin_email,
                display_name="Platform Admin", role=UserRole.platform_admin.value,
                status=UserStatus.active.value, password_hash=hash_password(settings.seed_admin_password),
            )
            session.add(admin)
            await session.flush()
            logger.info("seeded_admin_user", user_id=str(admin.id), email=admin.email)

        model_policy = (
            await session.execute(
                select(ModelPolicy).where(ModelPolicy.tenant_id == tenant.id, ModelPolicy.name == "phase0-default")
            )
        ).scalar_one_or_none()
        if model_policy is None:
            model_policy = ModelPolicy(
                id=new_id(), tenant_id=tenant.id, name="phase0-default",
                primary_provider=settings.default_model_provider, primary_model=settings.default_model_name,
                fallback_config={}, max_input_tokens=8000, max_output_tokens=8000,
                max_cost_per_task=2.00, timeout_seconds=60,
                retry_policy={"max_retries": 2, "backoff_seconds": 0.5},
            )
            session.add(model_policy)
            await session.flush()
            logger.info("seeded_model_policy", model_policy_id=str(model_policy.id),
                        provider=model_policy.primary_provider)

        atlas = (
            await session.execute(select(Agent).where(Agent.tenant_id == tenant.id, Agent.agent_code == "AGT-000001"))
        ).scalar_one_or_none()
        if atlas is None:
            atlas = Agent(
                id=new_id(), tenant_id=tenant.id, agent_code="AGT-000001", display_name="Atlas",
                description="Research Analyst", department="Research", role_name="Research Analyst",
                lifecycle_state=AgentLifecycleState.active.value, created_by=admin.id,
            )
            session.add(atlas)
            await session.flush()

            tool_policy = ToolPolicy.allow_only(
                [ToolName.artifact_write, ToolName.artifact_read, ToolName.knowledge_read]
            )
            version_payload = {
                "system_prompt": ATLAS_SYSTEM_PROMPT, "runtime_adapter": "custom_durable",
                "model_policy_id": str(model_policy.id), "autonomy_level": AutonomyLevel.a1.value,
                "tool_policy": tool_policy.model_dump(),
            }
            version = AgentVersion(
                id=new_id(), agent_id=atlas.id, version=1, system_prompt=ATLAS_SYSTEM_PROMPT,
                runtime_adapter="custom_durable", model_policy_id=model_policy.id,
                autonomy_level=AutonomyLevel.a1.value, tool_policy=tool_policy.model_dump(),
                memory_policy={}, settings={}, checksum=sha256_hex(str(version_payload)), created_by=admin.id,
            )
            session.add(version)
            await session.flush()

            atlas.active_version_id = version.id
            await session.flush()
            logger.info("seeded_atlas_agent", agent_id=str(atlas.id), version_id=str(version.id))

        claude_code_policy = (
            await session.execute(
                select(ModelPolicy).where(
                    ModelPolicy.tenant_id == tenant.id, ModelPolicy.name == "claude-code-external"
                )
            )
        ).scalar_one_or_none()
        if claude_code_policy is None:
            # Cosmetic only — no ModelGateway provider is ever registered for
            # "claude-code" and none needs to be; this row exists so Mission Control's
            # agent-creation form and the Agent Registry have something consistent to
            # display, matching Atlas's ModelPolicy shape.
            claude_code_policy = ModelPolicy(
                id=new_id(), tenant_id=tenant.id, name="claude-code-external",
                primary_provider="claude-code", primary_model="claude-code-session",
                fallback_config={}, max_input_tokens=0, max_output_tokens=0,
                max_cost_per_task=0, timeout_seconds=0, retry_policy={},
            )
            session.add(claude_code_policy)
            await session.flush()
            logger.info("seeded_claude_code_model_policy", model_policy_id=str(claude_code_policy.id))

        claude_code = (
            await session.execute(
                select(Agent).where(Agent.tenant_id == tenant.id, Agent.agent_code == "AGT-CLAUDE-CODE")
            )
        ).scalar_one_or_none()
        if claude_code is None:
            claude_code = Agent(
                id=new_id(), tenant_id=tenant.id, agent_code="AGT-CLAUDE-CODE", display_name="Claude Code",
                description=CLAUDE_CODE_DESCRIPTION, department="Engineering", role_name="External AI Agent",
                lifecycle_state=AgentLifecycleState.active.value, created_by=admin.id,
            )
            session.add(claude_code)
            await session.flush()

            tool_policy = ToolPolicy.allow_only(
                [ToolName.artifact_write, ToolName.artifact_read, ToolName.knowledge_read]
            )
            version_payload = {
                "system_prompt": CLAUDE_CODE_DESCRIPTION, "runtime_adapter": "external_manual",
                "model_policy_id": str(claude_code_policy.id), "autonomy_level": AutonomyLevel.a3.value,
                "tool_policy": tool_policy.model_dump(),
            }
            version = AgentVersion(
                id=new_id(), agent_id=claude_code.id, version=1, system_prompt=CLAUDE_CODE_DESCRIPTION,
                runtime_adapter="external_manual", model_policy_id=claude_code_policy.id,
                autonomy_level=AutonomyLevel.a3.value, tool_policy=tool_policy.model_dump(),
                memory_policy={}, settings={}, checksum=sha256_hex(str(version_payload)), created_by=admin.id,
            )
            session.add(version)
            await session.flush()

            claude_code.active_version_id = version.id
            await session.flush()
            logger.info("seeded_claude_code_agent", agent_id=str(claude_code.id), version_id=str(version.id))

        await session.commit()

    logger.info("seed_complete")


if __name__ == "__main__":
    asyncio.run(seed())
