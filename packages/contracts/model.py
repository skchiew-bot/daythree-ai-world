"""Model Gateway request/response contracts (spec §11).

`ModelProvider` protocol itself lives in `services/model-gateway` — this module only
holds the plain data shapes so the Mission Engine and Agent Runtime can reference them
without importing a specific provider or the gateway's routing internals.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ModelRequest(BaseModel):
    provider: str
    model: str
    system_prompt: str
    user_prompt: str
    max_output_tokens: int
    temperature: float = 0.2
    timeout_seconds: int = 60
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelResponse(BaseModel):
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    provider: str
    model: str
    finish_reason: str = "stop"
    # True when the provider returned text but no usage figures, so `input_tokens` and
    # `output_tokens` are conservative estimates rather than reported numbers (R0, ADR-013).
    usage_estimated: bool = False
    raw: Optional[dict[str, Any]] = None
