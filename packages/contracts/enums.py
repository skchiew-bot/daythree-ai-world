"""Every enumerated domain value in the Phase 0 spec, in one place.

Keeping these as plain `str` Enums (rather than native Postgres enum types) lets the
mission/task/agent state machines add or reorder states without an `ALTER TYPE`
migration — a deliberate trade against a small amount of DB-level type safety.
"""
from __future__ import annotations

from enum import Enum


class TenantStatus(str, Enum):
    active = "active"
    suspended = "suspended"


class UserRole(str, Enum):
    platform_admin = "platform_admin"
    tenant_admin = "tenant_admin"
    operator = "operator"
    auditor = "auditor"
    viewer = "viewer"


class UserStatus(str, Enum):
    active = "active"
    disabled = "disabled"


class AgentLifecycleState(str, Enum):
    draft = "draft"
    active = "active"
    suspended = "suspended"


class AutonomyLevel(str, Enum):
    a1 = "A1"
    a2 = "A2"
    a3 = "A3"


class RuntimeAdapterName(str, Enum):
    custom_durable = "custom_durable"
    langgraph = "langgraph"


class MissionStatus(str, Enum):
    draft = "draft"
    ready = "ready"
    running = "running"
    paused = "paused"
    failed = "failed"
    completed = "completed"
    cancelled = "cancelled"


class MissionPriority(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class TaskStatus(str, Enum):
    queued = "queued"
    running = "running"
    waiting = "waiting"
    failed = "failed"
    completed = "completed"
    cancelled = "cancelled"


class RuntimeCheckpointStatus(str, Enum):
    created = "created"
    resumed = "resumed"
    superseded = "superseded"


class ArtifactType(str, Enum):
    mission_output = "mission_output"
    raw_model_response = "raw_model_response"


class ModelInvocationStatus(str, Enum):
    requested = "requested"
    completed = "completed"
    failed = "failed"


class ToolName(str, Enum):
    artifact_write = "artifact.write"
    artifact_read = "artifact.read"
    knowledge_read = "knowledge.read"
    calculator_execute = "calculator.execute"


class ActorType(str, Enum):
    user = "user"
    agent = "agent"
    system = "system"


class EventType(str, Enum):
    agent_created = "agent.created"
    agent_version_created = "agent.version_created"
    agent_activated = "agent.activated"
    agent_suspended = "agent.suspended"

    mission_created = "mission.created"
    mission_started = "mission.started"
    mission_completed = "mission.completed"
    mission_failed = "mission.failed"
    # Not in spec §9's required list, but §8.6/§17 give missions a `cancelled` status
    # and a Mission Control "cancel" action — an audited action needs an event type
    # (spec §4 rule 3), so this is added rather than left silently unaudited.
    mission_cancelled = "mission.cancelled"

    task_created = "task.created"
    task_assigned = "task.assigned"
    task_started = "task.started"
    task_retry_started = "task.retry_started"
    task_completed = "task.completed"
    task_failed = "task.failed"

    runtime_checkpoint_created = "runtime.checkpoint_created"
    runtime_recovered = "runtime.recovered"

    model_requested = "model.requested"
    model_completed = "model.completed"
    model_failed = "model.failed"

    tool_requested = "tool.requested"
    tool_denied = "tool.denied"
    tool_completed = "tool.completed"
    tool_failed = "tool.failed"

    artifact_created = "artifact.created"
    artifact_version_created = "artifact.version_created"

    authorization_denied = "authorization.denied"
    budget_exceeded = "budget.exceeded"
