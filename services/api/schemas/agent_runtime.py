"""Request/response shapes for `POST`/`PATCH /api/v1/agent-runtime/sessions` (T1
deliverable 4/8). `extra="forbid"` plus this exact field set is the elevation guard
(T1-F13/T1-F11/T1-F10): no prompt, cwd, description, reason, autonomy, tool policy, model
policy or agent code can ever reach this router -- a client sending any of those gets a
plain 422 from FastAPI's own request validation, before any route code runs.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from contracts.enums import AgentRuntimeKind, AgentRuntimeOutcome
from contracts.ids import EntityId

_REF_PATTERN = r"^[A-Za-z0-9._-]{1,64}$"


class AgentRuntimeSessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: AgentRuntimeKind
    agent_type: Optional[str] = Field(default=None, max_length=512)
    # Required (and UUID-shaped) for kind="session"; a subagent spawn correlates via
    # `external_instance_ref` + `parent_external_session_ref` instead and never needs
    # its own session ref, so this is optional at the field level and enforced per-kind
    # below.
    external_session_ref: Optional[str] = Field(default=None, max_length=64)
    external_instance_ref: Optional[str] = Field(default=None, max_length=64)
    parent_external_session_ref: Optional[str] = Field(default=None, max_length=64)

    @field_validator("external_instance_ref", "parent_external_session_ref")
    @classmethod
    def _validate_ref_shape(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not re.match(_REF_PATTERN, value):
            raise ValueError("must be 1-64 characters of letters, digits, '.', '_' or '-'.")
        return value

    @model_validator(mode="after")
    def _validate_kind_specific_fields(self) -> "AgentRuntimeSessionCreateRequest":
        if self.kind == AgentRuntimeKind.session:
            # mission_code is the session uuid directly (build-plan condition C5): must
            # be a real UUID so `missions.title` always matches
            # `^Claude Code session [0-9a-f-]{36}$` (T1 acceptance test 13).
            if not self.external_session_ref:
                raise ValueError("external_session_ref is required for kind='session'.")
            try:
                UUID(self.external_session_ref)
            except ValueError as exc:
                raise ValueError("external_session_ref must be a UUID for kind='session'.") from exc
        if self.kind == AgentRuntimeKind.subagent:
            if not self.external_instance_ref:
                raise ValueError("external_instance_ref is required for kind='subagent'.")
            if not self.parent_external_session_ref:
                raise ValueError("parent_external_session_ref is required for kind='subagent'.")
        return self


class AgentRuntimeSessionUpdateRequest(BaseModel):
    """PATCH body: absent `outcome` is a heartbeat (bumps `last_heartbeat_at` only);
    a present `outcome` ends the runtime session (`ended_at` + the enum value)."""

    model_config = ConfigDict(extra="forbid")

    outcome: Optional[AgentRuntimeOutcome] = None


class AgentRuntimeSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    kind: str
    agent_id: Optional[EntityId]
    mission_id: Optional[EntityId]
    task_id: Optional[EntityId]
    external_session_ref: str
    external_instance_ref: Optional[str]
    parent_session_id: Optional[EntityId]
    started_at: datetime
    last_heartbeat_at: Optional[datetime]
    ended_at: Optional[datetime]
    outcome: Optional[str]
