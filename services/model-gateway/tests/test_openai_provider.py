import pytest

from model_gateway.providers.openai_provider import OpenAIProvider

pytestmark = pytest.mark.unit


def test_requires_an_api_key():
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIProvider(api_key="")


def test_constructs_with_a_key_present():
    provider = OpenAIProvider(api_key="sk-test-not-a-real-key")
    assert provider.provider_name == "openai"
