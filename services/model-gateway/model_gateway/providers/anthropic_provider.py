"""A real `ModelProvider` backed by the Anthropic API. Gated on `ANTHROPIC_API_KEY` —
never constructed unless a key is present, so importing this module never requires
network access and never fails in an environment with no key configured.
"""
from __future__ import annotations

import time

import anthropic

from contracts.model import ModelRequest, ModelResponse


class AnthropicProvider:
    provider_name = "anthropic"

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError(
                "AnthropicProvider requires ANTHROPIC_API_KEY. Use MockModelProvider "
                "(DEFAULT_MODEL_PROVIDER=mock) when no key is configured."
            )
        # max_retries=0: the SDK's own retries (default 2) would send up to 3 billed HTTP
        # requests for one gateway attempt that the write-ahead ledger cannot see.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)

    async def generate(self, request: ModelRequest) -> ModelResponse:
        start = time.monotonic()
        response = await self._client.messages.create(
            model=request.model,
            max_tokens=request.max_output_tokens,
            temperature=request.temperature,
            system=request.system_prompt,
            messages=[{"role": "user", "content": request.user_prompt}],
            timeout=request.timeout_seconds,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        text = "".join(block.text for block in response.content if block.type == "text")

        return ModelResponse(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=latency_ms,
            provider=self.provider_name,
            model=response.model,
            finish_reason=response.stop_reason or "stop",
            raw=response.model_dump(),
        )
