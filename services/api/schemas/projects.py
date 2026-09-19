from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

from contracts.ids import EntityId

# ADR-014 decision 2 / data-warden D12: 1-20 chars, starts with a letter or digit,
# uppercase letters/digits/underscore/hyphen only.
_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")
_CODE_MAX_LENGTH = 20
_NAME_MAX_LENGTH = 80


class ProjectCreateRequest(BaseModel):
    code: str
    name: str

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        if not (1 <= len(value) <= _CODE_MAX_LENGTH) or not _CODE_PATTERN.match(value):
            raise ValueError(
                "code must be 1-20 characters matching ^[A-Z0-9][A-Z0-9_-]*$"
            )
        return value

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not (1 <= len(value) <= _NAME_MAX_LENGTH):
            raise ValueError(f"name must be 1-{_NAME_MAX_LENGTH} characters")
        if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
            raise ValueError("name must not contain control characters")
        return value


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: EntityId
    code: str
    name: str
    status: str
    created_at: datetime
