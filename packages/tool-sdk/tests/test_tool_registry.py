import pytest

from contracts.policy import ToolPolicy
from tool_sdk.registry import ToolRegistry
from tool_sdk.tools import ToolContext

pytestmark = pytest.mark.unit

ALLOW_ALL = ToolPolicy(allow=["*"], deny=[])
ATLAS_POLICY = ToolPolicy(allow=["artifact.write", "artifact.read", "knowledge.read"], deny=["*"])


@pytest.mark.asyncio
async def test_calculator_execute_computes_arithmetic():
    registry = ToolRegistry()
    result = await registry.execute(
        "calculator.execute",
        {"expression": "(2 + 3) * 4"},
        ToolContext(),
        platform_policy=ALLOW_ALL,
        tenant_policy=ALLOW_ALL,
        agent_policy=ALLOW_ALL,
    )
    assert result.executed
    assert result.output["result"] == 20


@pytest.mark.asyncio
async def test_calculator_execute_rejects_unsafe_expression():
    registry = ToolRegistry()
    result = await registry.execute(
        "calculator.execute",
        {"expression": "__import__('os').system('echo hi')"},
        ToolContext(),
        platform_policy=ALLOW_ALL,
        tenant_policy=ALLOW_ALL,
        agent_policy=ALLOW_ALL,
    )
    assert result.decision.allowed is True
    assert result.error is not None
    assert result.output is None


@pytest.mark.asyncio
async def test_knowledge_read_returns_context_value():
    registry = ToolRegistry()
    context = ToolContext(available_context={"kpi_framework": "CSAT, FCR, AHT"})
    result = await registry.execute(
        "knowledge.read",
        {"key": "kpi_framework"},
        context,
        platform_policy=ALLOW_ALL,
        tenant_policy=ALLOW_ALL,
        agent_policy=ALLOW_ALL,
    )
    assert result.executed
    assert result.output == {"key": "kpi_framework", "found": True, "value": "CSAT, FCR, AHT"}


@pytest.mark.asyncio
async def test_unauthorized_tool_is_denied_before_execution_tc_p0_005():
    """Atlas (artifact.write/read + knowledge.read only) requests calculator.execute —
    denied at the registry choke point, never reaching a handler."""
    registry = ToolRegistry()
    result = await registry.execute(
        "calculator.execute",
        {"expression": "1+1"},
        ToolContext(),
        platform_policy=ALLOW_ALL,
        tenant_policy=ALLOW_ALL,
        agent_policy=ATLAS_POLICY,
    )
    assert result.executed is False
    assert result.decision.allowed is False
    assert result.output is None
    assert result.error is None  # denied before the handler ever ran


@pytest.mark.asyncio
async def test_artifact_write_without_bound_port_fails_cleanly():
    registry = ToolRegistry()
    result = await registry.execute(
        "artifact.write",
        {"title": "t", "content": "c"},
        ToolContext(artifact_port=None),
        platform_policy=ALLOW_ALL,
        tenant_policy=ALLOW_ALL,
        agent_policy=ATLAS_POLICY,
    )
    assert result.decision.allowed is True
    assert result.error is not None
