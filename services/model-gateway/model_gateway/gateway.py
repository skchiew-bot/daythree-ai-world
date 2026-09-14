"""The Model Gateway (spec §11): the only door to an LLM provider.

Owns routing, retries, timeout, token/cost-ceiling enforcement (via `policy_sdk.budgets`),
a circuit breaker, and request/response hashing. Deliberately does NOT own persistence —
`generate` returns a `ModelInvocationTelemetry` alongside the `ModelResponse`, and the
caller (Mission Engine / worker, which already holds the request-scoped DB session and
knows the tenant/mission/task/agent ids) is responsible for writing the `model_invocations`
row and emitting `model.*` events in the same transaction as the rest of the task's state
change. This keeps the gateway a pure, easily-unit-tested component with no DB dependency.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from common.hashing import sha256_hex
from contracts.enums import ModelInvocationStatus
from contracts.model import ModelRequest, ModelResponse
from contracts.policy import BudgetPolicy
from model_gateway.protocol import ModelProvider
from model_gateway.routing.circuit_breaker import CircuitBreaker, CircuitOpenError
from model_gateway.telemetry import ModelInvocationTelemetry, estimate_cost_usd
from policy_sdk.budgets import BudgetUsage, evaluate_budget


class BudgetExceededError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class ModelGatewayError(Exception):
    """Raised after retries are exhausted; wraps the last underlying provider error."""


@dataclass
class GenerateOutcome:
    response: ModelResponse
    telemetry: ModelInvocationTelemetry
    attempts: int


@dataclass
class ModelGateway:
    providers: dict[str, ModelProvider]
    circuit_breaker: CircuitBreaker = field(default_factory=CircuitBreaker)
    max_attempts: int = 3
    backoff_base_seconds: float = 0.5

    async def generate(
        self,
        request: ModelRequest,
        *,
        budget_policy: BudgetPolicy,
        usage: BudgetUsage,
        is_retry: bool = False,
    ) -> GenerateOutcome:
        budget_decision = evaluate_budget(
            budget_policy, usage, requested_output_tokens=request.max_output_tokens, is_retry=is_retry
        )
        if not budget_decision.allowed:
            raise BudgetExceededError(budget_decision.reason or "Budget exceeded.")

        provider = self.providers.get(request.provider)
        if provider is None:
            raise ModelGatewayError(f"No provider registered for '{request.provider}'.")

        request_hash = sha256_hex(request.model_dump_json())
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                self.circuit_breaker.before_call(request.provider)
                response = await asyncio.wait_for(
                    provider.generate(request), timeout=request.timeout_seconds
                )
                self.circuit_breaker.record_success(request.provider)

                cost = estimate_cost_usd(
                    request.provider, request.model, response.input_tokens, response.output_tokens
                )
                telemetry = ModelInvocationTelemetry(
                    provider=request.provider,
                    model=request.model,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    estimated_cost=cost,
                    latency_ms=response.latency_ms,
                    status=ModelInvocationStatus.completed,
                    request_hash=request_hash,
                    response_hash=sha256_hex(response.text),
                )
                return GenerateOutcome(response=response, telemetry=telemetry, attempts=attempt)

            except CircuitOpenError:
                raise
            except (asyncio.TimeoutError, Exception) as exc:  # noqa: BLE001
                last_error = exc
                self.circuit_breaker.record_failure(request.provider)
                if attempt < self.max_attempts:
                    await asyncio.sleep(self.backoff_base_seconds * (2 ** (attempt - 1)))
                continue

        raise ModelGatewayError(
            f"Model call to '{request.provider}/{request.model}' failed after "
            f"{self.max_attempts} attempts: {last_error}"
        ) from last_error
