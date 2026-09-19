from types import SimpleNamespace

import pytest

from model_gateway.providers.anthropic_provider import AnthropicProvider

pytestmark = pytest.mark.unit


def test_the_sdk_client_never_retries_on_its_own(monkeypatch):
    """Each SDK retry is another billed HTTP request the gateway's ledger cannot see."""
    seen = {}

    def _fake_client(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr("anthropic.AsyncAnthropic", _fake_client)
    AnthropicProvider(api_key="sk-ant-test-not-a-real-key")
    assert seen["max_retries"] == 0
