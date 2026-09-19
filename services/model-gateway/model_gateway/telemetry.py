from __future__ import annotations

import math
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from contracts.enums import ModelInvocationStatus
from model_gateway.errors import UnpricedModelError

# Per-1K-token USD pricing. The mock provider is always free (wildcard row). There is
# deliberately NO default price: a (provider, model) pair that is not listed raises
# `UnpricedModelError` before any provider call, because a silent default undercounted
# unlisted Opus-class models by 5x (R0, ADR-013 F3). Add a row here, with its source,
# before a new model is used.
#
# OpenAI rows: verified 2026-09-19 against OpenAI's public Standard-tier pricing page,
# https://developers.openai.com/api/docs/pricing (redirected from
# https://platform.openai.com/docs/pricing): gpt-4o $2.50 in / $10.00 out and
# gpt-4o-mini $0.15 in / $0.60 out, per 1M tokens (= the per-1K figures below).
# Anthropic rows: NOT re-verified in R0 (the operator's provider is OpenAI, ADR-013 O13);
# treat them as unverified until someone checks them against Anthropic's pricing page.
_PRICING_PER_1K_TOKENS: dict[tuple[str, str], tuple[Decimal, Decimal]] = {
    ("mock", "*"): (Decimal("0"), Decimal("0")),
    ("anthropic", "claude-sonnet-5"): (Decimal("0.003"), Decimal("0.015")),  # unverified
    ("anthropic", "claude-haiku-4-5-20251001"): (Decimal("0.001"), Decimal("0.005")),  # unverified
    ("anthropic", "claude-opus-5"): (Decimal("0.015"), Decimal("0.075")),  # unverified
    ("openai", "gpt-4o-mini"): (Decimal("0.00015"), Decimal("0.0006")),
    ("openai", "gpt-4o"): (Decimal("0.0025"), Decimal("0.01")),
}


def _price_for(provider: str, model: str) -> tuple[Decimal, Decimal]:
    price = _PRICING_PER_1K_TOKENS.get((provider, model), _PRICING_PER_1K_TOKENS.get((provider, "*")))
    if price is None:
        raise UnpricedModelError(provider, model)
    return price


def require_priced(provider: str, model: str) -> None:
    """Raises `UnpricedModelError` if no price is known. The gateway calls this before its
    first provider attempt so nothing ever runs at an unknown price."""
    _price_for(provider, model)


def estimate_cost_usd(provider: str, model: str, input_tokens: int, output_tokens: int) -> Decimal:
    input_price, output_price = _price_for(provider, model)
    return (Decimal(input_tokens) / 1000 * input_price) + (Decimal(output_tokens) / 1000 * output_price)


# --- Cost of an attempt that did not return usable usage numbers -----------------------
#
# POLICY (R0, ADR-013): never undercount. A timed-out (or otherwise failed) attempt may
# still have been accepted and billed by the provider, and the client cannot know what
# was generated. So unless the failure provably happened before billing, the attempt is
# charged as if it had consumed:
#   - input tokens : ceil(UTF-8 bytes of system + user prompt / 3). Real tokenizers average
#                    about 4 bytes/token for English and about 1 to 3 bytes/token for
#                    other scripts and code, so bytes/3 is an upper-leaning estimate.
#   - output tokens: the full `max_output_tokens` cap, the most the provider could have
#                    generated and billed.
# Failures that provably cannot have billed cost 0 (the attempt still counts as a call):
# an HTTP 4xx rejection from the provider (auth, validation, unknown model, rate limit)
# other than 408 Request Timeout. Everything else, meaning timeouts, connection errors,
# 5xx and unrecognised exceptions, is charged conservatively.
_BYTES_PER_INPUT_TOKEN_ESTIMATE = 3
_HTTP_REQUEST_TIMEOUT = 408


def estimate_input_tokens(system_prompt: str, user_prompt: str) -> int:
    size = len((system_prompt + user_prompt).encode("utf-8"))
    return math.ceil(size / _BYTES_PER_INPUT_TOKEN_ESTIMATE)


def is_provably_unbilled(error: BaseException) -> bool:
    """True only for an HTTP 4xx rejection (both the OpenAI and Anthropic SDK errors carry
    an integer `status_code`); 408 is a timeout and stays conservative."""
    status = getattr(error, "status_code", None)
    return isinstance(status, int) and 400 <= status < 500 and status != _HTTP_REQUEST_TIMEOUT


def estimate_failed_attempt(
    provider: str, model: str, *, system_prompt: str, user_prompt: str, max_output_tokens: int,
    error: BaseException,
) -> tuple[int, int, Decimal]:
    """Returns (input_tokens, output_tokens, cost_usd) to record for a failed attempt.
    The token counts are estimates, not provider-reported; see the policy above."""
    if is_provably_unbilled(error):
        return 0, 0, Decimal("0")
    tokens_in = estimate_input_tokens(system_prompt, user_prompt)
    return tokens_in, max_output_tokens, estimate_cost_usd(provider, model, tokens_in, max_output_tokens)


class ModelInvocationTelemetry(BaseModel):
    """Everything `model_invocations` (spec §8.11) needs, minus the tenant/mission/task/
    agent ids — those are known to the caller (Mission Engine), not to the gateway.

    For `status=failed` rows the token counts and cost are conservative estimates (see
    `estimate_failed_attempt`), not provider-reported usage.
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
