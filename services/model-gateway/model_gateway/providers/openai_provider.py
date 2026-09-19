"""A real `ModelProvider` backed by the OpenAI API. Gated on `OPENAI_API_KEY` — never
constructed unless a key is present, so importing this module never requires network
access and never fails in an environment with no key configured. Mirrors
`anthropic_provider.py`'s structure exactly; see that module's docstring for the same
reasoning.
"""
from __future__ import annotations

import time

import openai
import structlog

from contracts.model import ModelRequest, ModelResponse
from model_gateway.telemetry import estimate_input_tokens

logger = structlog.get_logger(__name__)

# OpenAI's Chat Completions reference marks `max_tokens` deprecated in favour of
# `max_completion_tokens` and "not compatible with o-series models" (checked 2026-09-19:
# https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create).
# GPT-4-family models keep accepting `max_tokens`; every other model (o1/o3/o4, gpt-5, and
# anything newer) gets the documented replacement, so an unknown future model fails safe
# toward the parameter OpenAI recommends.
_MAX_TOKENS_MODEL_PREFIXES = ("gpt-4", "gpt-3.5", "chatgpt-4o")


def _model_param_kwargs(request: ModelRequest) -> dict[str, int | float]:
    """Token cap and temperature, in the form the target model accepts. Reasoning models
    (o-series, gpt-5 family) take `max_completion_tokens` and reject a non-default
    `temperature` with a 400, so it is only sent on the GPT-4 branch."""
    if request.model.startswith(_MAX_TOKENS_MODEL_PREFIXES):
        return {"max_tokens": request.max_output_tokens, "temperature": request.temperature}
    return {"max_completion_tokens": request.max_output_tokens}


class OpenAIProvider:
    provider_name = "openai"

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError(
                "OpenAIProvider requires OPENAI_API_KEY. Use MockModelProvider "
                "(DEFAULT_MODEL_PROVIDER=mock) when no key is configured."
            )
        # max_retries=0: the SDK's own retries (default 2) would send up to 3 billed HTTP
        # requests for one gateway attempt that the write-ahead ledger cannot see. The
        # gateway owns retries, and every one of them is budgeted and recorded.
        self._client = openai.AsyncOpenAI(api_key=api_key, max_retries=0)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        start = time.monotonic()
        response = await self._client.chat.completions.create(
            model=request.model,
            **_model_param_kwargs(request),
            messages=[
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            timeout=request.timeout_seconds,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        choice = response.choices[0]
        text = choice.message.content or ""
        input_tokens, output_tokens, estimated = _usage_or_estimate(response, request)

        return ModelResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            usage_estimated=estimated,
            latency_ms=latency_ms,
            provider=self.provider_name,
            model=response.model,
            finish_reason=choice.finish_reason or "stop",
            raw=response.model_dump(),
        )


def _usage_or_estimate(response, request: ModelRequest) -> tuple[int, int, bool]:
    """Reported usage, or, if the provider returned text without any, the conservative
    figures used for an attempt of unknown size (prompt bytes / 3 in, the full output cap
    out) flagged as estimated. A returned completion is never recorded as free."""
    if response.usage is not None:
        return response.usage.prompt_tokens, response.usage.completion_tokens, False
    logger.warning("openai_usage_missing_estimating", model=request.model)
    return estimate_input_tokens(request.system_prompt, request.user_prompt), request.max_output_tokens, True
