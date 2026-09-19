"""A minimal per-provider circuit breaker: after `failure_threshold` consecutive
failures, the breaker opens for `cooldown_seconds` and every call fails fast without
even attempting the provider. This is intentionally simple (no half-open probe queue,
no sliding window) — enough to stop a Phase 0 mission from hammering a provider that is
clearly down, not a production-grade resilience library.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from model_gateway.errors import ModelGatewayError


class CircuitOpenError(ModelGatewayError):
    """A ModelGatewayError so the mission engine fails the task cleanly instead of leaving
    it `running` for the orphan sweep to requeue (R0). No request was sent, so `attempts`
    is empty unless the circuit opened part-way through a call's own retries."""

    def __init__(self, provider: str, retry_after_seconds: float):
        self.provider = provider
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Circuit open for provider '{provider}'; retry after {retry_after_seconds:.0f}s.")


@dataclass
class _ProviderState:
    consecutive_failures: int = 0
    opened_at: float | None = None


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    cooldown_seconds: float = 30.0
    _state: dict[str, _ProviderState] = field(default_factory=dict)

    def _get(self, provider: str) -> _ProviderState:
        return self._state.setdefault(provider, _ProviderState())

    def before_call(self, provider: str) -> None:
        state = self._get(provider)
        if state.opened_at is None:
            return
        elapsed = time.monotonic() - state.opened_at
        if elapsed < self.cooldown_seconds:
            raise CircuitOpenError(provider, self.cooldown_seconds - elapsed)
        # Cooldown elapsed: allow one probe call through (half-open).
        state.opened_at = None
        state.consecutive_failures = 0

    def record_success(self, provider: str) -> None:
        state = self._get(provider)
        state.consecutive_failures = 0
        state.opened_at = None

    def record_failure(self, provider: str) -> None:
        state = self._get(provider)
        state.consecutive_failures += 1
        if state.consecutive_failures >= self.failure_threshold and state.opened_at is None:
            state.opened_at = time.monotonic()
