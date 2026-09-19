from types import SimpleNamespace

import pytest

from contracts.model import ModelRequest
from model_gateway.providers.openai_provider import OpenAIProvider

pytestmark = pytest.mark.unit


def test_requires_an_api_key():
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIProvider(api_key="")


def test_constructs_with_a_key_present():
    provider = OpenAIProvider(api_key="sk-test-not-a-real-key")
    assert provider.provider_name == "openai"


# --- R0 (ADR-013): the token-cap parameter must be one the target model accepts ---------
# OpenAI's Chat Completions reference marks `max_tokens` deprecated in favour of
# `max_completion_tokens` and "not compatible with o-series models" (source:
# https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create,
# checked 2026-09-19). GPT-4-family models keep accepting `max_tokens`.


class _FakeCompletions:
    def __init__(self):
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
            model=kwargs["model"],
            model_dump=lambda: {},
        )


def _provider_with_fake_client() -> tuple[OpenAIProvider, _FakeCompletions]:
    provider = OpenAIProvider(api_key="sk-test-not-a-real-key")
    completions = _FakeCompletions()
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return provider, completions


def _request(model: str) -> ModelRequest:
    return ModelRequest(
        provider="openai", model=model, system_prompt="s", user_prompt="u", max_output_tokens=777
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["gpt-4o", "gpt-4o-mini", "gpt-4.1-mini", "gpt-3.5-turbo"])
async def test_gpt4_family_keeps_max_tokens(model):
    provider, completions = _provider_with_fake_client()
    await provider.generate(_request(model))
    assert completions.kwargs["max_tokens"] == 777
    assert "max_completion_tokens" not in completions.kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["o1", "o3-mini", "o4-mini", "gpt-5-mini", "gpt-5-nano"])
async def test_reasoning_and_newer_models_use_max_completion_tokens(model):
    provider, completions = _provider_with_fake_client()
    await provider.generate(_request(model))
    assert completions.kwargs["max_completion_tokens"] == 777
    assert "max_tokens" not in completions.kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["gpt-4o", "gpt-4o-mini"])
async def test_temperature_is_sent_to_models_that_accept_it(model):
    provider, completions = _provider_with_fake_client()
    await provider.generate(_request(model))
    assert completions.kwargs["temperature"] == 0.2


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["o1", "o3-mini", "o4-mini", "gpt-5-mini"])
async def test_temperature_is_omitted_for_reasoning_models(model):
    """Reasoning models reject a non-default temperature with a 400."""
    provider, completions = _provider_with_fake_client()
    await provider.generate(_request(model))
    assert "temperature" not in completions.kwargs


def test_the_sdk_client_never_retries_on_its_own(monkeypatch):
    """Each SDK retry is another billed HTTP request the gateway's ledger cannot see."""
    seen = {}

    def _fake_client(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr("openai.AsyncOpenAI", _fake_client)
    OpenAIProvider(api_key="sk-test-not-a-real-key")
    assert seen["max_retries"] == 0


@pytest.mark.asyncio
async def test_a_success_without_usage_is_estimated_conservatively_and_flagged():
    provider, completions = _provider_with_fake_client()
    original = completions.create

    async def _no_usage(**kwargs):
        response = await original(**kwargs)
        response.usage = None
        return response

    completions.create = _no_usage
    response = await provider.generate(_request("gpt-4o"))

    assert response.usage_estimated is True
    assert response.input_tokens >= 1  # prompt bytes / 3, never zero for a non-empty prompt
    assert response.output_tokens == 777  # the full max_output_tokens: nothing was reported


@pytest.mark.asyncio
async def test_reported_usage_is_not_flagged_as_estimated():
    provider, _ = _provider_with_fake_client()
    response = await provider.generate(_request("gpt-4o"))
    assert response.usage_estimated is False
    assert (response.input_tokens, response.output_tokens) == (3, 2)
