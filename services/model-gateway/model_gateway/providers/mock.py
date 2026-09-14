"""A `ModelProvider` that makes no network call and costs nothing — the default for
the Phase 0 demonstration mission so the whole loop is provable with zero external
dependencies. Output is deterministic (same prompt → same output) and always validates
against `contracts.output_contract.MissionOutput`.

It deliberately does NOT pretend to have done real research — every section says so
explicitly, honoring spec §18's "never invent evidence" for Atlas even when the
"model" behind Atlas is this mock.
"""
from __future__ import annotations

import json
import time

from common.hashing import sha256_hex
from contracts.model import ModelRequest, ModelResponse

_OUTLINE = [
    "Objective",
    "Business problem",
    "Required data",
    "Core capabilities",
    "Integration considerations",
    "KPI framework",
    "Risks",
    "Assumptions",
    "Recommended MVP boundary",
    "Open questions",
]


class MockModelProvider:
    provider_name = "mock"

    async def generate(self, request: ModelRequest) -> ModelResponse:
        start = time.monotonic()

        sections = [
            {
                "heading": heading,
                "content": (
                    f"[MOCK OUTPUT — no external model was called] Placeholder content for "
                    f"'{heading}', generated deterministically from the task instructions. "
                    f"This is a Phase 0 walking-skeleton response, not real analysis; no "
                    f"evidence is claimed here per the 'never invent evidence' instruction."
                ),
            }
            for heading in _OUTLINE
        ]
        payload = {
            "title": f"[MOCK] {request.metadata.get('mission_title', 'Mission Output')}",
            "executive_summary": (
                "This artifact was produced by the deterministic MockModelProvider "
                "(no ANTHROPIC_API_KEY configured / mock provider selected). It exists to "
                "prove the end-to-end mission pipeline, not to answer the objective."
            ),
            "sections": sections,
            "assumptions": ["A real model provider was not configured for this run."],
            "risks": ["This output must not be used for any real business decision."],
            "open_questions": ["What does the real model say once a provider is configured?"],
        }
        text = json.dumps(payload)
        latency_ms = int((time.monotonic() - start) * 1000) or 1

        return ModelResponse(
            text=text,
            input_tokens=max(1, len(request.system_prompt + request.user_prompt) // 4),
            output_tokens=max(1, len(text) // 4),
            latency_ms=latency_ms,
            provider=self.provider_name,
            model=request.model,
            finish_reason="stop",
            raw={"mock": True, "request_hash": sha256_hex(request.model_dump_json())},
        )
