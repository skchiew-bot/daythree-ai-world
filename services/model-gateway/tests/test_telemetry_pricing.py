"""R0 (ADR-013): pricing is a closed table (no default price) and the failed-attempt cost
policy is explicit and conservative.
"""
from decimal import Decimal

import pytest

import model_gateway.telemetry as telemetry
from model_gateway.errors import UnpricedModelError
from model_gateway.telemetry import (
    estimate_cost_usd,
    estimate_failed_attempt,
    estimate_input_tokens,
)

pytestmark = pytest.mark.unit


class _HttpError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code


def test_unpriced_pair_raises_a_typed_error():
    with pytest.raises(UnpricedModelError, match="gpt-unheard-of"):
        estimate_cost_usd("openai", "gpt-unheard-of", 10, 10)


def test_no_default_price_survives():
    assert not hasattr(telemetry, "_DEFAULT_PRICE")


def test_mock_is_free_for_any_model_name():
    assert estimate_cost_usd("mock", "whatever", 10_000, 10_000) == Decimal("0")


def test_known_openai_prices():
    # gpt-4o: $2.50 / $10.00 per 1M tokens; gpt-4o-mini: $0.15 / $0.60 per 1M tokens
    assert estimate_cost_usd("openai", "gpt-4o", 1_000_000, 0) == Decimal("2.5")
    assert estimate_cost_usd("openai", "gpt-4o", 0, 1_000_000) == Decimal("10")
    assert estimate_cost_usd("openai", "gpt-4o-mini", 1_000_000, 1_000_000) == Decimal("0.75")


def test_input_token_estimate_is_utf8_bytes_over_three_rounded_up():
    assert estimate_input_tokens("a" * 299, "") == 100  # ceil(299 / 3)
    assert estimate_input_tokens("", "") == 0
    assert estimate_input_tokens("é", "") == 1  # 2 bytes -> 1 token, never 0 for non-empty


def test_timeout_is_charged_estimated_input_plus_full_max_output():
    tokens_in, tokens_out, cost = estimate_failed_attempt(
        "openai", "gpt-4o", system_prompt="a" * 300, user_prompt="", max_output_tokens=1000,
        error=TimeoutError(),
    )
    assert (tokens_in, tokens_out) == (100, 1000)
    assert cost == Decimal("0.1") * Decimal("0.0025") + Decimal("1") * Decimal("0.01")


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429])
def test_provider_4xx_rejections_cost_nothing(status):
    assert estimate_failed_attempt(
        "openai", "gpt-4o", system_prompt="x" * 900, user_prompt="y", max_output_tokens=1000,
        error=_HttpError(status),
    ) == (0, 0, Decimal("0"))


@pytest.mark.parametrize("error", [_HttpError(408), _HttpError(500), _HttpError(503), RuntimeError("?")])
def test_anything_that_might_have_billed_is_charged_conservatively(error):
    _, tokens_out, cost = estimate_failed_attempt(
        "openai", "gpt-4o", system_prompt="x" * 30, user_prompt="", max_output_tokens=500, error=error
    )
    assert tokens_out == 500
    assert cost > 0


def test_worst_case_attempt_is_estimated_input_plus_full_max_output():
    from model_gateway.telemetry import estimate_worst_case_attempt

    assert estimate_worst_case_attempt(
        "openai", "gpt-4o", system_prompt="a" * 300, user_prompt="", max_output_tokens=1000
    ) == (100, 1000, Decimal("0.01025"))


def test_worst_case_attempt_of_an_unpriced_model_raises():
    from model_gateway.telemetry import estimate_worst_case_attempt

    with pytest.raises(UnpricedModelError):
        estimate_worst_case_attempt("openai", "nope", system_prompt="a", user_prompt="", max_output_tokens=1)


def test_failed_attempt_on_mock_is_free():
    assert estimate_failed_attempt(
        "mock", "m", system_prompt="x" * 300, user_prompt="", max_output_tokens=1000, error=TimeoutError()
    )[2] == Decimal("0")
