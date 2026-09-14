"""The ModelProvider protocol — spec §11, verbatim."""
from __future__ import annotations

from typing import Protocol

from contracts.model import ModelRequest, ModelResponse


class ModelProvider(Protocol):
    async def generate(self, request: ModelRequest) -> ModelResponse: ...
