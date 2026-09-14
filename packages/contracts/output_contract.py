"""The mission output schema (spec §21) that every mission's model output must validate against."""
from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

__all__ = ["OutputSection", "MissionOutput", "validate_mission_output", "OUTPUT_JSON_SCHEMA"]


class OutputSection(BaseModel):
    heading: str
    content: str


class MissionOutput(BaseModel):
    title: str
    executive_summary: str
    sections: list[OutputSection]
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


OUTPUT_JSON_SCHEMA = MissionOutput.model_json_schema()


def validate_mission_output(raw_text: str) -> tuple[MissionOutput | None, str | None]:
    """Returns (parsed, None) on success or (None, error_message) on failure.

    `error_message` is meant to be fed back into a single repair re-prompt (spec §21) —
    it must be safe to include in a prompt, so it never echoes back full raw content.
    """
    import json

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return None, f"Output was not valid JSON: {exc.msg} at line {exc.lineno} col {exc.colno}."

    try:
        return MissionOutput.model_validate(payload), None
    except ValidationError as exc:
        return None, f"Output did not match the required schema: {exc.errors()}"
