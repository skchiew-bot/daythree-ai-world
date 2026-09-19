"""The Model Gateway (spec §11): the only door to an LLM provider.

Owns routing, retries, timeout, token/cost-ceiling enforcement (via `policy_sdk.budgets`),
a circuit breaker, and request/response hashing. Deliberately does NOT own persistence —
the caller (Mission Engine / worker, which already holds the request-scoped DB session and
knows the tenant/mission/task/agent ids) supplies an `AttemptLedger` and writes the
`model_invocations` rows through it. This keeps the gateway free of any DB dependency.

Budget enforcement (R0, ADR-013): the budget is checked before the first provider attempt
using the usage the caller supplies (committed calls/cost/elapsed for the task), and again
before EVERY further attempt with this call's own attempts, their estimated cost and
elapsed time added, with `is_retry=True`. The cost ceiling is checked against spent plus
the attempt's own worst case. A timeout counts as a billed call.

Write-ahead charging: when a ledger is supplied, every attempt is recorded BEFORE it is
sent (a committed `requested` row at the worst-case cost) and finished afterwards. If the
process dies, the lease is lost or a commit fails, the write-ahead charge stands, so the
committed charges are always >= the provider requests that may have been sent. A failed
write-ahead means no request is sent.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from common.hashing import sha256_hex
from contracts.enums import ModelInvocationStatus
from contracts.model import ModelRequest, ModelResponse
from contracts.policy import BudgetPolicy
from model_gateway.errors import ModelGatewayError, UnpricedModelError
from model_gateway.protocol import AttemptLedger, ModelProvider
from model_gateway.routing.circuit_breaker import CircuitBreaker, CircuitOpenError
from model_gateway.telemetry import (
    ModelInvocationTelemetry,
    estimate_cost_usd,
    estimate_failed_attempt,
    estimate_worst_case_attempt,
    is_permanent_rejection,
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
class _Call:
    """State of one `generate()` call."""

    request: ModelRequest
    request_hash: str
    worst_case_cost_usd: float
    ledger: AttemptLedger | None
    started: float = field(default_factory=time.monotonic)
    failed: list[ModelInvocationTelemetry] = field(default_factory=list)


@dataclass
class _Attempt:
    attempt_id: Any
    response: ModelResponse | None = None
    error: Exception | None = None


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
        ledger: AttemptLedger | None = None,
    ) -> GenerateOutcome:
        provider, call = self._admit(request, budget_policy, usage, is_retry, ledger)
        last_error: Exception | None = None

        for attempt_number in range(1, self.max_attempts + 1):
            self._check_circuit(call)
            attempt = await self._attempt(provider, call)
            if attempt.error is None:
                return await self._succeed(call, attempt, attempt_number)

            last_error = attempt.error
            if is_permanent_rejection(attempt.error):
                raise ModelGatewayError(
                    f"Model call to '{request.provider}/{request.model}' was rejected by the "
                    f"provider and will not be retried: {attempt.error}",
                    attempts=call.failed,
                ) from attempt.error
            if attempt_number < self.max_attempts:
                self._require_retry_budget(call, budget_policy, usage, attempt_number)
                await asyncio.sleep(self.backoff_base_seconds * (2 ** (attempt_number - 1)))

        raise ModelGatewayError(
            f"Model call to '{request.provider}/{request.model}' failed after "
            f"{self.max_attempts} attempts: {last_error}",
            attempts=call.failed,
        ) from last_error

    def _admit(
        self, request: ModelRequest, policy: BudgetPolicy, usage: BudgetUsage, is_retry: bool,
        ledger: AttemptLedger | None,
    ) -> tuple[ModelProvider, _Call]:
        """Everything that must hold before the first provider attempt: a registered
        provider, a known price (`UnpricedModelError` otherwise), and budget headroom for the
        call's worst case."""
        provider = self.providers.get(request.provider)
        if provider is None:
            raise ModelGatewayError(f"No provider registered for '{request.provider}'.")
        *_, worst_case_cost = estimate_worst_case_attempt(
            request.provider, request.model, system_prompt=request.system_prompt,
            user_prompt=request.user_prompt, max_output_tokens=request.max_output_tokens,
        )
        decision = evaluate_budget(
            policy, usage, requested_output_tokens=request.max_output_tokens, is_retry=is_retry,
            worst_case_cost_usd=float(worst_case_cost),
        )
        if not decision.allowed:
            raise BudgetExceededError(decision.reason or "Budget exceeded.")
        call = _Call(request, sha256_hex(request.model_dump_json()), float(worst_case_cost), ledger)
        return provider, call

    def _check_circuit(self, call: _Call) -> None:
        try:
            self.circuit_breaker.before_call(call.request.provider)
        except CircuitOpenError as exc:
            exc.attempts = tuple(call.failed)
            raise

    async def _attempt(self, provider: ModelProvider, call: _Call) -> _Attempt:
        """One provider request, written ahead and finished on the ledger."""
        request = call.request
        attempt = _Attempt(attempt_id=await self._write_ahead(call))
        attempt_started = time.monotonic()
        try:
            attempt.response = await asyncio.wait_for(provider.generate(request), timeout=request.timeout_seconds)
        except Exception as exc:  # noqa: BLE001 - includes asyncio.TimeoutError; cancellation is not swallowed
            attempt.error = exc
            if not is_permanent_rejection(exc):  # a bad request says nothing about provider health
                self.circuit_breaker.record_failure(request.provider)
            failure = _failed_attempt_telemetry(call, exc, time.monotonic() - attempt_started)
            call.failed.append(failure)
            await self._finish(call, attempt.attempt_id, failure)
        else:
            self.circuit_breaker.record_success(request.provider)
        return attempt

    async def _write_ahead(self, call: _Call) -> Any:
        if call.ledger is None:
            return None
        request = call.request
        tokens_in, tokens_out, cost = estimate_worst_case_attempt(
            request.provider, request.model, system_prompt=request.system_prompt,
            user_prompt=request.user_prompt, max_output_tokens=request.max_output_tokens,
        )
        return await call.ledger.begin_attempt(
            ModelInvocationTelemetry(
                provider=request.provider, model=request.model, input_tokens=tokens_in,
                output_tokens=tokens_out, estimated_cost=cost, latency_ms=0,
                status=ModelInvocationStatus.requested, request_hash=call.request_hash,
            )
        )

    @staticmethod
    async def _finish(call: _Call, attempt_id: Any, outcome: ModelInvocationTelemetry) -> None:
        if call.ledger is not None:
            await call.ledger.finish_attempt(attempt_id, outcome)

    async def _succeed(self, call: _Call, attempt: _Attempt, attempt_number: int) -> GenerateOutcome:
        request, response = call.request, attempt.response
        telemetry = ModelInvocationTelemetry(
            provider=request.provider, model=request.model, input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            estimated_cost=estimate_cost_usd(
                request.provider, request.model, response.input_tokens, response.output_tokens
            ),
            latency_ms=response.latency_ms, status=ModelInvocationStatus.completed,
            request_hash=call.request_hash, response_hash=sha256_hex(response.text),
            usage_estimated=response.usage_estimated,
        )
        await self._finish(call, attempt.attempt_id, telemetry)
        return GenerateOutcome(
            response=response, telemetry=telemetry, attempts=attempt_number, failed_attempts=call.failed
        )

    def _require_retry_budget(
        self, call: _Call, policy: BudgetPolicy, incoming: BudgetUsage, attempt_number: int
    ) -> None:
        """Re-evaluates the budget before attempt `attempt_number + 1`, with this call's own
        attempts counted. `retries_made` is retries already spent, so the first retry sees
        `incoming.retries_made + 0`."""
        so_far = BudgetUsage(
            calls_made=incoming.calls_made + len(call.failed),
            cost_spent_usd=incoming.cost_spent_usd + float(sum(t.estimated_cost for t in call.failed)),
            elapsed_minutes=incoming.elapsed_minutes + (time.monotonic() - call.started) / 60,
            retries_made=incoming.retries_made + (attempt_number - 1),
        )
        decision = evaluate_budget(
            policy, so_far, requested_output_tokens=call.request.max_output_tokens, is_retry=True,
            worst_case_cost_usd=call.worst_case_cost_usd,
        )
        if not decision.allowed:
            raise BudgetExceededError(decision.reason or "Budget exceeded.", attempts=call.failed)


def _failed_attempt_telemetry(call: _Call, error: BaseException, elapsed_seconds: float) -> ModelInvocationTelemetry:
    request = call.request
    tokens_in, tokens_out, cost = estimate_failed_attempt(
        request.provider, request.model, system_prompt=request.system_prompt,
        user_prompt=request.user_prompt, max_output_tokens=request.max_output_tokens, error=error,
    )
    return ModelInvocationTelemetry(
        provider=request.provider, model=request.model, input_tokens=tokens_in, output_tokens=tokens_out,
        estimated_cost=cost, latency_ms=int(elapsed_seconds * 1000), status=ModelInvocationStatus.failed,
        request_hash=call.request_hash, response_hash=None,
    )
