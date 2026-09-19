import json

import pytest

from contracts.enums import ModelInvocationStatus
from contracts.model import ModelRequest, ModelResponse
from contracts.policy import BudgetPolicy
from model_gateway.gateway import BudgetExceededError, ModelGateway, ModelGatewayError
from model_gateway.providers.mock import MockModelProvider
from model_gateway.routing.circuit_breaker import CircuitBreaker, CircuitOpenError
from policy_sdk.budgets import BudgetUsage

pytestmark = pytest.mark.unit


def make_request(**overrides) -> ModelRequest:
    defaults = dict(
        provider="mock", model="claude-sonnet-5", system_prompt="sys", user_prompt="hi",
        max_output_tokens=1000, timeout_seconds=5,
    )
    defaults.update(overrides)
    return ModelRequest(**defaults)


@pytest.mark.asyncio
async def test_mock_provider_generates_schema_valid_output():
    gateway = ModelGateway(providers={"mock": MockModelProvider()})
    outcome = await gateway.generate(
        make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage()
    )
    assert outcome.telemetry.status == ModelInvocationStatus.completed
    assert outcome.attempts == 1
    payload = json.loads(outcome.response.text)
    assert "title" in payload and "sections" in payload


@pytest.mark.asyncio
async def test_budget_exceeded_blocks_the_call_tc_p0_009():
    gateway = ModelGateway(providers={"mock": MockModelProvider()})
    with pytest.raises(BudgetExceededError):
        await gateway.generate(
            make_request(),
            budget_policy=BudgetPolicy(max_model_calls=1),
            usage=BudgetUsage(calls_made=1),
        )


class _FlakyProvider:
    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("simulated transient provider failure")
        return ModelResponse(
            text="{}", input_tokens=1, output_tokens=1, latency_ms=1,
            provider="mock", model=request.model,
        )


@pytest.mark.asyncio
async def test_retries_then_succeeds_tc_p0_008():
    provider = _FlakyProvider(fail_times=1)
    gateway = ModelGateway(providers={"mock": provider}, max_attempts=3, backoff_base_seconds=0)
    outcome = await gateway.generate(
        make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage()
    )
    assert outcome.attempts == 2
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_retries_exhausted_raises_gateway_error():
    provider = _FlakyProvider(fail_times=10)
    gateway = ModelGateway(providers={"mock": provider}, max_attempts=2, backoff_base_seconds=0)
    with pytest.raises(ModelGatewayError):
        await gateway.generate(
            make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage()
        )
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold_failures():
    provider = _FlakyProvider(fail_times=999)
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
    gateway = ModelGateway(
        providers={"mock": provider}, circuit_breaker=breaker, max_attempts=1, backoff_base_seconds=0
    )

    for _ in range(2):
        with pytest.raises(ModelGatewayError):
            await gateway.generate(
                make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage()
            )

    with pytest.raises(CircuitOpenError):
        await gateway.generate(
            make_request(), budget_policy=BudgetPolicy(), usage=BudgetUsage()
        )
