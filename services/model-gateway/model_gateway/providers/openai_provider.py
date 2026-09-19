"""A real `ModelProvider` backed by the OpenAI API. Gated on `OPENAI_API_KEY` — never
constructed unless a key is present, so importing this module never requires network
access and never fails in an environment with no key configured. Mirrors
`anthropic_provider.py`'s structure exactly; see that module's docstring for the same
reasoning.
"""
from __future__ import annotations

import time

import openai

from contracts.model import ModelRequest, ModelResponse


# OpenAI's Chat Completions reference marks `max_tokens` deprecated in favour of
# `max_completion_tokens` and "not compatible with o-series models" (checked 2026-09-19:
# https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create).
# GPT-4-family models keep accepting `max_tokens`; every other model (o1/o3/o4, gpt-5, and
# anything newer) gets the documented replacement, so an unknown future model fails safe
# toward the parameter OpenAI recommends.
_MAX_TOKENS_MODEL_PREFIXES = ("gpt-4", "gpt-3.5", "chatgpt-4o")


def _token_cap_kwargs(model: str, max_output_tokens: int) -> dict[str, int]:
    if model.startswith(_MAX_TOKENS_MODEL_PREFIXES):
        return {"max_tokens": max_output_tokens}
    return {"max_completion_tokens": max_output_tokens}


class OpenAIProvider:
    provider_name = "openai"

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError(
                "OpenAIProvider requires OPENAI_API_KEY. Use MockModelProvider "
                "(DEFAULT_MODEL_PROVIDER=mock) when no key is configured."
            )
        self._client = openai.AsyncOpenAI(api_key=api_key)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        start = time.monotonic()
        response = await self._client.chat.completions.create(
            model=request.model,
            **_token_cap_kwargs(request.model, request.max_output_tokens),
            temperature=request.temperature,
            messages=[
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
            timeout=request.timeout_seconds,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        choice = response.choices[0]
        text = choice.message.content or ""

        return ModelResponse(
            text=text,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            latency_ms=latency_ms,
            provider=self.provider_name,
            model=response.model,
            finish_reason=choice.finish_reason or "stop",
            raw=response.model_dump(),
        )
