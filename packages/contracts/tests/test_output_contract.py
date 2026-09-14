import json

import pytest

from contracts.output_contract import MissionOutput, validate_mission_output

pytestmark = pytest.mark.unit

VALID_PAYLOAD = {
    "title": "Repeated Interaction Analysis — Requirements",
    "executive_summary": "A concise summary.",
    "sections": [{"heading": "Objective", "content": "..."}],
    "assumptions": ["Assumption one"],
    "risks": ["Risk one"],
    "open_questions": ["Question one"],
}


def test_valid_output_parses_successfully():
    parsed, error = validate_mission_output(json.dumps(VALID_PAYLOAD))
    assert error is None
    assert isinstance(parsed, MissionOutput)
    assert parsed.title == VALID_PAYLOAD["title"]


def test_invalid_json_returns_error_not_exception():
    parsed, error = validate_mission_output("{not valid json")
    assert parsed is None
    assert "not valid JSON" in error


def test_schema_violation_returns_error_not_exception():
    bad_payload = dict(VALID_PAYLOAD)
    del bad_payload["title"]
    parsed, error = validate_mission_output(json.dumps(bad_payload))
    assert parsed is None
    assert error is not None
    assert "schema" in error
