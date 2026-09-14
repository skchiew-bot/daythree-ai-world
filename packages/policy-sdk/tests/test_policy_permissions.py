"""Unit tests for the permission evaluator (spec §12, TC-P0-005)."""
import pytest

from contracts.policy import ToolPolicy
from policy_sdk.permissions import (
    PermissionDenied,
    evaluate_tool_access,
    require_tool_access,
)

pytestmark = pytest.mark.unit

PLATFORM_ALLOW_ALL = ToolPolicy(allow=["*"], deny=[])
ATLAS_AGENT_POLICY = ToolPolicy(
    allow=["artifact.write", "artifact.read", "knowledge.read"], deny=["*"]
)
TENANT_ALLOW_ALL = ToolPolicy(allow=["*"], deny=[])


def test_agent_can_use_its_own_allowed_tool():
    decision = evaluate_tool_access(
        "artifact.write",
        platform_policy=PLATFORM_ALLOW_ALL,
        tenant_policy=TENANT_ALLOW_ALL,
        agent_policy=ATLAS_AGENT_POLICY,
    )
    assert decision.allowed is True


def test_unauthorized_tool_is_denied_tc_p0_005():
    """Atlas requests a shell/network tool it was never granted — TC-P0-005."""
    decision = evaluate_tool_access(
        "shell.execute",
        platform_policy=PLATFORM_ALLOW_ALL,
        tenant_policy=TENANT_ALLOW_ALL,
        agent_policy=ATLAS_AGENT_POLICY,
    )
    assert decision.allowed is False
    assert decision.reason is not None


def test_tool_outside_the_known_universe_is_denied():
    decision = evaluate_tool_access(
        "totally.unknown.tool",
        platform_policy=PLATFORM_ALLOW_ALL,
        tenant_policy=TENANT_ALLOW_ALL,
        agent_policy=ATLAS_AGENT_POLICY,
    )
    assert decision.allowed is False


def test_platform_deny_wins_even_if_agent_allows():
    """Deny always wins (spec §12) — a platform-level deny overrides an agent allow."""
    platform_denies_calculator = ToolPolicy(allow=["*"], deny=["calculator.execute"])
    agent_allows_calculator = ToolPolicy(allow=["calculator.execute"], deny=[])

    decision = evaluate_tool_access(
        "calculator.execute",
        platform_policy=platform_denies_calculator,
        tenant_policy=TENANT_ALLOW_ALL,
        agent_policy=agent_allows_calculator,
    )
    assert decision.allowed is False
    assert decision.denied_by_scope == "platform"


def test_mission_policy_can_further_restrict_when_present():
    mission_denies_everything = ToolPolicy(allow=[], deny=["*"])

    decision = evaluate_tool_access(
        "artifact.write",
        platform_policy=PLATFORM_ALLOW_ALL,
        tenant_policy=TENANT_ALLOW_ALL,
        agent_policy=ATLAS_AGENT_POLICY,
        mission_policy=mission_denies_everything,
    )
    assert decision.allowed is False
    assert decision.denied_by_scope == "mission"


def test_require_tool_access_raises_on_denial():
    with pytest.raises(PermissionDenied):
        require_tool_access(
            "shell.execute",
            platform_policy=PLATFORM_ALLOW_ALL,
            tenant_policy=TENANT_ALLOW_ALL,
            agent_policy=ATLAS_AGENT_POLICY,
        )


def test_require_tool_access_passes_silently_when_allowed():
    require_tool_access(
        "knowledge.read",
        platform_policy=PLATFORM_ALLOW_ALL,
        tenant_policy=TENANT_ALLOW_ALL,
        agent_policy=ATLAS_AGENT_POLICY,
    )
