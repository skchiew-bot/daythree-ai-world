from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from contracts.ids import EntityId


class ModelPolicyCreateRequest(BaseModel):
    """Deliberately just name/provider/model (guardian-gatekeeper, PATCH /model-policies
    gate review, condition A4): `max_cost_per_task`, `max_input_tokens`, `timeout_seconds`
    and `retry_policy` are NOT accepted here because they are not enforced anywhere at
    runtime today (task_executor only ever reads `primary_provider`/`primary_model` off
    this row) — exposing them would let a caller set a "cost ceiling" that does nothing,
    recorded as if it were real in the audit trail."""

    name: str
    primary_provider: str
    primary_model: str


class ModelPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    name: str
    primary_provider: str
    primary_model: str
    created_at: datetime
