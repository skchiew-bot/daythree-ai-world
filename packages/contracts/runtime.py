"""Agent Runtime Adapter contract shapes (spec §10).

The `AgentRuntimeAdapter` Protocol itself lives in `services/agent-runtime` so the
Mission Engine only ever imports these plain data shapes plus the protocol — never a
concrete adapter class (spec §10: "no business logic may call [a specific runtime]
directly outside the adapter layer").
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from contracts.enums import RuntimeCheckpointStatus
from contracts.ids import EntityId
from contracts.model import ModelResponse
from contracts.policy import BudgetPolicy, ToolPolicy


class RunContext(BaseModel):
    """Everything the runtime needs to execute one task, assembled by the Mission Engine."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    tenant_id: EntityId
    mission_id: EntityId
    task_id: EntityId
    agent_id: EntityId
    agent_version_id: EntityId
    correlation_id: EntityId

    system_prompt: str
    mission_objective: str
    task_instructions: str
    tool_policy: ToolPolicy
    budget_policy: BudgetPolicy
    available_context: dict[str, Any] = Field(default_factory=dict)

    model_provider: str
    model_name: str
    resume_from: Optional["Checkpoint"] = None


class RunHandle(BaseModel):
    run_id: EntityId
    context: RunContext


class Checkpoint(BaseModel):
    """Persisted as one `runtime_checkpoints` row per spec §8.8."""

    checkpoint_id: Optional[EntityId] = None
    run_id: EntityId
    task_id: EntityId
    mission_id: EntityId
    agent_id: EntityId
    sequence: int
    status: RuntimeCheckpointStatus
    state: dict[str, Any]


class RunResult(BaseModel):
    run_id: EntityId
    succeeded: bool
    output_text: Optional[str] = None
    model_response: Optional[ModelResponse] = None
    # Plain dict, not `model_gateway.telemetry.ModelInvocationTelemetry` — contracts must
    # not import from a service package (spec §4 rule 7/8: swappable runtime/provider).
    # The Mission Engine reconstructs a typed telemetry object from this before persisting
    # the `model_invocations` row.
    model_telemetry: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    final_checkpoint: Optional[Checkpoint] = None


RunContext.model_rebuild()
