"""T1 acceptance test 10 (persona resolution): exact allow-list only, never a formatted
lookup, so hostile/malformed `agent_type` values can never resolve onto Atlas
(`AGT-000001`) or `AGT-CLAUDE-CODE`.
"""
from __future__ import annotations

import pytest

from api.persona_registry import GENERAL_PERSONA_CODE, PERSONA_SLOT_CAP, resolve_persona

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "agent_type",
    ["planner", "architect", "code-reviewer", "tdd-guide", "security-reviewer"],
)
def test_known_persona_names_resolve_to_their_own_constant_code(agent_type):
    persona = resolve_persona(agent_type)
    assert persona.agent_code != GENERAL_PERSONA_CODE
    assert persona.agent_code.startswith("AGT-CC-")


@pytest.mark.parametrize(
    "agent_type",
    [
        "000001",
        "../",
        "AGT-000001",
        "AGT-CLAUDE-CODE",
        "Planner",  # case-sensitive: not an exact match
        " planner",
        "",
        "x" * 500,
        "☃" * 500,
        None,
    ],
)
def test_unknown_or_hostile_agent_types_bucket_to_general_never_atlas_or_claude_code(agent_type):
    persona = resolve_persona(agent_type)
    assert persona.agent_code == GENERAL_PERSONA_CODE
    assert persona.agent_code not in {"AGT-000001", "AGT-CLAUDE-CODE"}


def test_persona_slot_cap_is_twenty_five():
    assert PERSONA_SLOT_CAP == 25
