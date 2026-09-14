"""The single source of truth for which provider names `ModelGateway.providers` will
actually contain for a given `Settings` — used both to build the gateway (worker/deps.py)
and to validate a `ModelPolicy.primary_provider` value at write time (api/routes/
model_policies.py), so the two can never drift (guardian-gatekeeper, PATCH /model-policies
gate review, condition A3). "mock" is always available; "anthropic"/"openai" only when
their key is configured, matching build_model_gateway's own conditional registration.
"""
from __future__ import annotations

from common.config import Settings


def available_provider_names(settings: Settings) -> frozenset[str]:
    names = {"mock"}
    if settings.anthropic_api_key:
        names.add("anthropic")
    if settings.openai_api_key:
        names.add("openai")
    return frozenset(names)
