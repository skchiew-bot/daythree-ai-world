"""The ModelProvider protocol — spec §11, verbatim — and the write-ahead ledger port."""
from __future__ import annotations

from typing import Any, Protocol

from contracts.model import ModelRequest, ModelResponse
from model_gateway.telemetry import ModelInvocationTelemetry


class ModelProvider(Protocol):
    async def generate(self, request: ModelRequest) -> ModelResponse: ...


class AttemptLedger(Protocol):
    """Where the gateway records every provider attempt BEFORE it is sent (R0, ADR-013).

    `begin_attempt` must durably commit a conservative charge (status `requested`, the
    worst-case cost) and return a handle; if it raises, no provider request is made.
    `finish_attempt` replaces that charge with the actual outcome (actual usage on success,
    the conservative failure charge or 0 for a provably unbilled rejection). If it is never
    called (crash, cancellation, commit failure) the write-ahead charge simply stands, so
    committed charges are always >= the requests that may have been sent.
    """

    async def begin_attempt(self, worst_case: ModelInvocationTelemetry) -> Any: ...

    async def finish_attempt(self, attempt_id: Any, outcome: ModelInvocationTelemetry) -> None: ...
