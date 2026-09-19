"""Server-side persona registry (ADR-010, T1 deliverable 7): the hook reports a bare
`agent_type` string; every other attribute -- agent_code, autonomy level, tool policy --
comes from THIS table, never from the hook's own request body (T1-F10). Codes are fixed
constants, never formatted from input, so a hostile or malformed `agent_type` can never
resolve onto an existing agent_code like `AGT-000001` (Atlas) or `AGT-CLAUDE-CODE`.

Initial roster is ADR-011 operator decision O1 (the five personas the operator actually
delegates to today); every other `agent_type` value buckets to `AGT-CC-GENERAL`. Autonomy
defaults to A1 and tool policy to fully deny (the build plan's "default A1 and the most
restrictive tool policy unless ADR-010 says otherwise" -- ADR-010 does not name a looser
policy for any of these, so all six personas here are A1 / deny-all).
"""
from __future__ import annotations

from dataclasses import dataclass

from contracts.enums import AutonomyLevel
from contracts.policy import ToolPolicy

# Hard per-tenant cap on auto-activated personas (ADR-010 B4 / T1-F14). The database also
# enforces this via `agent_runtime_persona_slots`'s CHECK(slot < 25) and its
# UNIQUE(tenant_id, slot) index -- this constant is what the claim loop reads to know when
# to give up rather than loop forever.
PERSONA_SLOT_CAP = 25

GENERAL_PERSONA_CODE = "AGT-CC-GENERAL"


@dataclass(frozen=True)
class PersonaDefinition:
    agent_code: str
    display_name: str
    autonomy_level: AutonomyLevel
    tool_policy: ToolPolicy


_DENY_ALL = ToolPolicy.allow_only([])

_REGISTRY: dict[str, PersonaDefinition] = {
    "planner": PersonaDefinition("AGT-CC-PLANNER", "Planner", AutonomyLevel.a1, _DENY_ALL),
    "architect": PersonaDefinition("AGT-CC-ARCHITECT", "Architect", AutonomyLevel.a1, _DENY_ALL),
    "code-reviewer": PersonaDefinition("AGT-CC-CODE-REVIEWER", "Code Reviewer", AutonomyLevel.a1, _DENY_ALL),
    "tdd-guide": PersonaDefinition("AGT-CC-TDD-GUIDE", "TDD Guide", AutonomyLevel.a1, _DENY_ALL),
    "security-reviewer": PersonaDefinition(
        "AGT-CC-SECURITY-REVIEWER", "Security Reviewer", AutonomyLevel.a1, _DENY_ALL
    ),
}

GENERAL_PERSONA = PersonaDefinition(GENERAL_PERSONA_CODE, "Claude Code (general)", AutonomyLevel.a1, _DENY_ALL)


def resolve_persona(agent_type: str | None) -> PersonaDefinition:
    """Exact allow-list lookup only -- never derives a code from `agent_type` (T1-F10).
    Anything that isn't one of the five known keys (an empty string, path-traversal-
    looking input, 500 chars of unicode, an existing agent_code like "AGT-000001")
    buckets to the general persona rather than raising: an unrecognized subagent type is
    an expected, not exceptional, case."""
    if agent_type is None:
        return GENERAL_PERSONA
    return _REGISTRY.get(agent_type, GENERAL_PERSONA)
