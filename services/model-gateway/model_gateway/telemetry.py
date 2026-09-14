from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from contracts.enums import ModelInvocationStatus

# Per-1K-token USD pricing. Mock provider is always free. Extend as new models/providers
# are added — deliberately a flat table rather than a pricing SDK call, since Phase 0
# only needs a believable cost ceiling, not billing-grade accuracy.
_PRICING_PER_1K_TOKENS: dict[tuple[str, str], tuple[Decimal, Decimal]] = {
    ("mock", "*"): (Decimal("0"), Decimal("0")),
    ("anthropic", "claude-sonnet-5"): (Decimal("0.003"), Decimal("0.015")),
    ("anthropic", "claude-haiku-4-5-20251001"): (Decimal("0.001"), Decimal("0.005")),
    ("anthropic", "claude-opus-5"): (Decimal("0.015"), Decimal("0.075")),
    ("openai", "gpt-4o-mini"): (Decimal("0.00015"), Decimal("0.0006")),
    ("openai", "gpt-4o"): (Decimal("0.0025"), Decimal("0.01")),
}
_DEFAULT_PRICE = (Decimal("0.003"), Decimal("0.015"))


def estimate_cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int) -> Decimal:
    if provider == "mock":
        return Decimal("0")
    input_price, output_price = _PRICING_PER_1K_TOKENS.get(
        (provider, model), _PRICING_PER_1K_TOKENS.get((provider, "*"), _DEFAULT_PRICE)
    )
    return (Decimal(input_tokens) / 1000 * input_price) + (Decimal(output_tokens) / 1000 * output_price)


class ModelInvocationTelemetry(BaseModel):
    """Everything `model_invocations` (spec §8.11) needs, minus the tenant/mission/task/
    agent ids — those are known to the caller (Mission Engine), not to the gateway.
    """

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost: Decimal
    latency_ms: int
    status: ModelInvocationStatus
    request_hash: str
    response_hash: Optional[str] = None
