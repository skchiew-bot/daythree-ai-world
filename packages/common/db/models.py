"""SQLAlchemy 2.x async models for every table in spec §8, plus the minimal additions
Phase 0 needs to actually enforce the spec's idempotency and auth requirements:

- `users.password_hash` — spec §23 requires local password auth; the table in §8.2
  doesn't list a credential column, so one is added here (never logged, never returned
  by any API schema — see `services/api/schemas`).
- `artifacts.logical_output_slot` — spec §14's idempotent-commit key is
  `unique(task_id, artifact_type, logical_output_slot, committed_version)`; `version`
  in §8.9 serves as `committed_version`, and `logical_output_slot` (default
  `"primary"`) is added so the exact constraint in the spec can be declared.
- `tasks.idempotency_key` is UNIQUE — spec §14 "every task receives an idempotency_key".
- `missions.assigned_agent_id` — spec §8.6 doesn't list it, but spec §17 Page 4 (Mission
  Control) requires an "assigned agent" field at mission-creation time, and spec §13
  step 4 assigns the agent before the first task exists. This column holds that
  mission-level assignment; the Mission Engine copies it onto the one Phase 0 task's
  `tasks.assigned_agent_id` (§8.7, already in the spec) when the task is created.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from common.db.base import Base
from contracts.enums import (
    AgentLifecycleState,
    ArtifactType,
    AutonomyLevel,
    MissionPriority,
    MissionStatus,
    ModelInvocationStatus,
    RiskLevel,
    RuntimeCheckpointStatus,
    TaskStatus,
    TenantStatus,
    UserRole,
    UserStatus,
)
from contracts.ids import EntityId, new_id

# Every timestamp in this app is timezone-aware (contracts.events uses
# datetime.now(timezone.utc) everywhere) — without an explicit timezone=True here,
# SQLAlchemy maps Mapped[datetime] to Postgres TIMESTAMP WITHOUT TIME ZONE, and
# asyncpg's codec raises `can't subtract offset-naive and offset-aware datetimes`
# the moment an aware Python datetime (e.g. AuditEvent.occurred_at from an
# EventEnvelope) is bound to it. Found via CI's first real run against Postgres —
# no unit test catches this since none of them touch a real asyncpg codec.
TZDateTime = DateTime(timezone=True)

UUIDPK = Mapped[EntityId]


def _pk() -> Mapped[EntityId]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[EntityId] = _pk()
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[TenantStatus] = mapped_column(String(32), default=TenantStatus.active)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[EntityId] = _pk()
    tenant_id: Mapped[EntityId] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(32), nullable=False)
    status: Mapped[UserStatus] = mapped_column(String(32), default=UserStatus.active)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)


class ModelPolicy(Base):
    __tablename__ = "model_policies"

    id: Mapped[EntityId] = _pk()
    tenant_id: Mapped[EntityId] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    primary_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_model: Mapped[str] = mapped_column(String(128), nullable=False)
    fallback_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    max_input_tokens: Mapped[int] = mapped_column(Integer, default=8000)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=4000)
    max_cost_per_task: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("2.00"))
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60)
    retry_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[EntityId] = _pk()
    tenant_id: Mapped[EntityId] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    agent_code: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    role_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    lifecycle_state: Mapped[AgentLifecycleState] = mapped_column(
        String(32), default=AgentLifecycleState.draft
    )
    active_version_id: Mapped[Optional[EntityId]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_versions.id", use_alter=True), nullable=True
    )
    created_by: Mapped[Optional[EntityId]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now(), onupdate=func.now())

    versions: Mapped[list["AgentVersion"]] = relationship(
        back_populates="agent", foreign_keys="AgentVersion.agent_id"
    )

    __table_args__ = (UniqueConstraint("tenant_id", "agent_code", name="uq_agents_tenant_code"),)


class AgentVersion(Base):
    __tablename__ = "agent_versions"

    id: Mapped[EntityId] = _pk()
    agent_id: Mapped[EntityId] = mapped_column(ForeignKey("agents.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    system_prompt: Mapped[str] = mapped_column(String, nullable=False)
    runtime_adapter: Mapped[str] = mapped_column(String(64), nullable=False)
    model_policy_id: Mapped[EntityId] = mapped_column(ForeignKey("model_policies.id"), nullable=False)
    autonomy_level: Mapped[AutonomyLevel] = mapped_column(String(8), default=AutonomyLevel.a1)
    tool_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    memory_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[Optional[EntityId]] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    agent: Mapped["Agent"] = relationship(back_populates="versions", foreign_keys=[agent_id])

    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"),)


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[EntityId] = _pk()
    tenant_id: Mapped[EntityId] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    mission_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    objective: Mapped[str] = mapped_column(String, nullable=False)
    requested_by: Mapped[Optional[EntityId]] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[MissionStatus] = mapped_column(String(32), default=MissionStatus.draft)
    priority: Mapped[MissionPriority] = mapped_column(String(16), default=MissionPriority.normal)
    risk_level: Mapped[RiskLevel] = mapped_column(String(16), default=RiskLevel.low)
    budget_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    assigned_agent_id: Mapped[Optional[EntityId]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime, nullable=True)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[EntityId] = _pk()
    mission_id: Mapped[EntityId] = mapped_column(ForeignKey("missions.id"), nullable=False)
    assigned_agent_id: Mapped[EntityId] = mapped_column(ForeignKey("agents.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    instructions: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(String(32), default=TaskStatus.queued)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    budget_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    input_context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    output_artifact_id: Mapped[Optional[EntityId]] = mapped_column(UUID(as_uuid=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())


class RuntimeCheckpoint(Base):
    __tablename__ = "runtime_checkpoints"

    id: Mapped[EntityId] = _pk()
    mission_id: Mapped[EntityId] = mapped_column(ForeignKey("missions.id"), nullable=False)
    task_id: Mapped[EntityId] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    agent_id: Mapped[EntityId] = mapped_column(ForeignKey("agents.id"), nullable=False)
    checkpoint_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[RuntimeCheckpointStatus] = mapped_column(
        String(32), default=RuntimeCheckpointStatus.created
    )
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("task_id", "checkpoint_sequence", name="uq_checkpoints_task_sequence"),
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[EntityId] = _pk()
    tenant_id: Mapped[EntityId] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    mission_id: Mapped[EntityId] = mapped_column(ForeignKey("missions.id"), nullable=False)
    task_id: Mapped[EntityId] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    agent_id: Mapped[EntityId] = mapped_column(ForeignKey("agents.id"), nullable=False)
    agent_version_id: Mapped[EntityId] = mapped_column(ForeignKey("agent_versions.id"), nullable=False)
    artifact_type: Mapped[ArtifactType] = mapped_column(String(64), nullable=False)
    logical_output_slot: Mapped[str] = mapped_column(String(64), default="primary")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    artifact_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint(
            "task_id", "artifact_type", "logical_output_slot", "version",
            name="uq_artifacts_idempotent_commit",
        ),
    )


class AuditEvent(Base):
    """Append-only. No update/delete path is exposed anywhere in the codebase."""

    __tablename__ = "audit_events"

    id: Mapped[EntityId] = _pk()
    tenant_id: Mapped[EntityId] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[Optional[EntityId]] = mapped_column(UUID(as_uuid=True), nullable=True)
    mission_id: Mapped[Optional[EntityId]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("missions.id"), nullable=True
    )
    task_id: Mapped[Optional[EntityId]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True
    )
    agent_id: Mapped[Optional[EntityId]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id"), nullable=True
    )
    correlation_id: Mapped[EntityId] = mapped_column(UUID(as_uuid=True), nullable=False)
    causation_id: Mapped[Optional[EntityId]] = mapped_column(UUID(as_uuid=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())


class ModelInvocation(Base):
    __tablename__ = "model_invocations"
    __table_args__ = (
        # Per-task usage (SqlUsageProvider: called before every model call) and per-agent
        # spend over time (ADR-013 metering). Migration 0003b creates these on existing DBs.
        Index("ix_model_invocations_task_id", "task_id"),
        Index("ix_model_invocations_tenant_agent_created", "tenant_id", "agent_id", "created_at"),
    )

    id: Mapped[EntityId] = _pk()
    tenant_id: Mapped[EntityId] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    mission_id: Mapped[EntityId] = mapped_column(ForeignKey("missions.id"), nullable=False)
    task_id: Mapped[EntityId] = mapped_column(ForeignKey("tasks.id"), nullable=False)
    agent_id: Mapped[EntityId] = mapped_column(ForeignKey("agents.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=Decimal("0"))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[ModelInvocationStatus] = mapped_column(String(32), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())


class ExternalAgentStatus(Base):
    """Not in spec §8 — a Phase 0-adjacent addition (see the 3D World page) for
    agents that live *outside* Daythree's own governed mission engine (a Claude Code
    session, an external script) to report a live status so they can be visualized
    alongside Atlas. Deliberately outside the governed loop: no budget enforcement,
    no audit_events entries — just a last-known-status row. The write endpoint
    (`PUT /{name}/status`) is role-gated and rate-limited (ADR-010 gate review, C1);
    it is not open to every authenticated caller."""

    __tablename__ = "external_agent_statuses"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_external_agent_statuses_tenant_name"),)

    id: Mapped[EntityId] = _pk()
    tenant_id: Mapped[EntityId] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    job_description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())


class AgentRoomAssignment(Base):
    """Per-tenant apartment room for a governed agent (ADR-009). Presentation-layer
    only — never gates `POST /api/v1/agents` (spec's admission control is untouched).
    `packages/common/rooms.py` owns the floor/room slot math; this table just persists
    the assignment so a returning agent gets back the *same* room rather than a
    recomputed one.

    The two partial unique indexes below (active rows only, `released_at IS NULL`)
    are the actual concurrency guarantee — not application-level check-then-act,
    consistent with the idempotency approach used elsewhere (artifacts' commit
    constraint, tasks' idempotency_key): one prevents two agents double-booking the
    same room, the other prevents one agent from holding two active rooms at once.
    """

    __tablename__ = "agent_room_assignments"
    __table_args__ = (
        CheckConstraint("room_index >= 1 AND room_index <= 4", name="ck_agent_room_assignments_room_index"),
        CheckConstraint("floor >= 1", name="ck_agent_room_assignments_floor"),
        Index(
            "uq_agent_room_assignments_active_room",
            "tenant_id", "floor", "room_index",
            unique=True, postgresql_where=text("released_at IS NULL"),
        ),
        Index(
            "uq_agent_room_assignments_active_agent",
            "tenant_id", "agent_id",
            unique=True, postgresql_where=text("released_at IS NULL"),
        ),
    )

    id: Mapped[EntityId] = _pk()
    tenant_id: Mapped[EntityId] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    agent_id: Mapped[EntityId] = mapped_column(ForeignKey("agents.id"), nullable=False)
    floor: Mapped[int] = mapped_column(Integer, nullable=False)
    room_index: Mapped[int] = mapped_column(Integer, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    released_at: Mapped[Optional[datetime]] = mapped_column(TZDateTime, nullable=True)
