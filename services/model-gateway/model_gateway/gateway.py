"""The Model Gateway (spec §11): the only door to an LLM provider.

Owns routing, retries, timeout, token/cost-ceiling enforcement (via `policy_sdk.budgets`),
a circuit breaker, and request/response hashing. Deliberately does NOT own persistence —
`generate` returns a `ModelInvocationTelemetry` alongside the `ModelResponse`, and the
caller (Mission Engine / worker, which already holds the request-scoped DB session and
knows the tenant/mission/task/agent ids) is responsible for writing the `model_invocations`
row and emitting `model.*` events in the same transaction as the rest of the task's state
change. This keeps the gateway a pure, easily-unit-tested component with no DB dependency.

Budget enforcement (R0, ADR-013): the budget is checked before the first provider attempt
using the usage the caller supplies (committed calls/cost/elapsed for the task), and again
before EVERY further attempt with this call's own attempts, their estimated cost and
elapsed time added, with `is_retry=True`. Every attempt, including failed and timed-out
ones, is reported back as telemetry (on the outcome, or on the raised error) because a
failed attempt can still be billed; a timeout counts as a billed call.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from common.hashing import sha256_hex
from contracts.enums import ModelInvocationStatus
from contracts.model import ModelRequest, ModelResponse
from contracts.policy import BudgetPolicy
from model_gateway.errors import ModelGatewayError, UnpricedModelError
from model_gateway.protocol import ModelProvider
from model_gateway.routing.circuit_breaker import CircuitBreaker, CircuitOpenError
from model_gateway.telemetry import (
    ModelInvocationTelemetry,
    estimate_cost_usd,
    estimate_failed_attempt,
    require_priced,
)
from policy_sdk.budgets import BudgetUsage, evaluate_budget

__all__ = [
    "BudgetExceededError", "GenerateOutcome", "ModelGateway", "ModelGatewayError", "UnpricedModelError",
]


class BudgetExceededError(Exception):
    def __init__(self, reason: str, *, attempts: tuple = ()):
        self.reason = reason
        self.attempts = tuple(attempts)
        super().__init__(reason)


@dataclass
class GenerateOutcome:
    response: ModelResponse
    telemetry: ModelInvocationTelemetry
    attempts: int
    failed_attempts: list[ModelInvocationTelemetry] = field(default_factory=list)


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
        require_priced(request.provider, request.model)  # nothing runs at an unknown price

        request_hash = sha256_hex(request.model_dump_json())
        started = time.monotonic()
        failed_attempts: list[ModelInvocationTelemetry] = []
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                self.circuit_breaker.before_call(request.provider)
            except CircuitOpenError as exc:
                if not failed_attempts:
                    raise
                raise ModelGatewayError(
                    f"Model call to '{request.provider}/{request.model}' stopped after "
                    f"{len(failed_attempts)} failed attempt(s): {exc}",
                    attempts=failed_attempts,
                ) from exc

            attempt_started = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    provider.generate(request), timeout=request.timeout_seconds
                )
            except Exception as exc:  # noqa: BLE001 - includes asyncio.TimeoutError; cancellation is not swallowed
                last_error = exc
                self.circuit_breaker.record_failure(request.provider)
                failed_attempts.append(
                    _failed_attempt_telemetry(request, request_hash, exc, time.monotonic() - attempt_started)
                )
                if attempt < self.max_attempts:
                    retry_decision = evaluate_budget(
                        budget_policy,
                        _usage_including_this_call(usage, failed_attempts, started, attempt),
                        requested_output_tokens=request.max_output_tokens,
                        is_retry=True,
                    )
                    if not retry_decision.allowed:
                        raise BudgetExceededError(
                            retry_decision.reason or "Budget exceeded.", attempts=failed_attempts
                        ) from exc
                    await asyncio.sleep(self.backoff_base_seconds * (2 ** (attempt - 1)))
                continue

            self.circuit_breaker.record_success(request.provider)
            telemetry = ModelInvocationTelemetry(
                provider=request.provider,
                model=request.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                estimated_cost=estimate_cost_usd(
                    request.provider, request.model, response.input_tokens, response.output_tokens
                ),
                latency_ms=response.latency_ms,
                status=ModelInvocationStatus.completed,
                request_hash=request_hash,
                response_hash=sha256_hex(response.text),
            )
            return GenerateOutcome(
                response=response, telemetry=telemetry, attempts=attempt, failed_attempts=failed_attempts
            )

        raise ModelGatewayError(
            f"Model call to '{request.provider}/{request.model}' failed after "
            f"{self.max_attempts} attempts: {last_error}",
            attempts=failed_attempts,
        ) from last_error


def _failed_attempt_telemetry(
    request: ModelRequest, request_hash: str, error: BaseException, elapsed_seconds: float
) -> ModelInvocationTelemetry:
    tokens_in, tokens_out, cost = estimate_failed_attempt(
        request.provider, request.model, system_prompt=request.system_prompt,
        user_prompt=request.user_prompt, max_output_tokens=request.max_output_tokens, error=error,
    )
    return ModelInvocationTelemetry(
        provider=request.provider, model=request.model, input_tokens=tokens_in, output_tokens=tokens_out,
        estimated_cost=cost, latency_ms=int(elapsed_seconds * 1000), status=ModelInvocationStatus.failed,
        request_hash=request_hash, response_hash=None,
    )


def _usage_including_this_call(
    incoming: BudgetUsage, failed_attempts: list[ModelInvocationTelemetry], started: float, attempt: int
) -> BudgetUsage:
    """Usage as seen by the budget check just before attempt `attempt + 1`: the caller's
    committed usage plus every attempt already made in this call. `retries_made` counts
    retries already spent, so the first retry sees `incoming.retries_made + 0`."""
    return BudgetUsage(
        calls_made=incoming.calls_made + len(failed_attempts),
        cost_spent_usd=incoming.cost_spent_usd + float(sum(t.estimated_cost for t in failed_attempts)),
        elapsed_minutes=incoming.elapsed_minutes + (time.monotonic() - started) / 60,
        retries_made=incoming.retries_made + (attempt - 1),
    )
