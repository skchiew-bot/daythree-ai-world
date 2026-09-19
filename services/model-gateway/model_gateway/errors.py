"""Gateway error types. Kept apart from `gateway.py` so `telemetry.py` (which the gateway
imports) can raise them without a circular import.
"""
from __future__ import annotations


class ModelGatewayError(Exception):
    """Raised when a model call cannot be completed; wraps the last underlying provider
    error when there was one.

    `attempts` holds `ModelInvocationTelemetry` for every provider attempt that was made
    before the failure (status=failed), so the caller can persist them: a failed attempt
    can still have been billed (R0, ADR-013).
    """

    def __init__(self, message: str, *, attempts: tuple = ()):
        super().__init__(message)
        self.attempts = tuple(attempts)


class UnpricedModelError(ModelGatewayError):
    """No price is known for this (provider, model). Raised before any provider call:
    nothing may run at an unknown price (R0, ADR-013)."""

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model
        super().__init__(
            f"No price is configured for model '{provider}/{model}'. Add it to "
            f"model_gateway.telemetry._PRICING_PER_1K_TOKENS before using it."
        )
