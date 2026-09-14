"""Shapes for tool policy and budget policy (spec §12, §22).

The evaluators that *apply* these shapes live in `packages/policy-sdk` — this module
only defines what a policy document looks like, so agents/tenants/missions can each
declare one without depending on the evaluator's implementation.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from contracts.enums import ToolName


class ToolPolicy(BaseModel):
    """`allow`/`deny` lists of tool names.

    `"*"` in `allow` means "everything" (subject to the other scopes' intersection and
    to any specific tool name in `deny`). `"*"` in `deny` is the spec §12 example's
    default-deny marker ("nothing except what `allow` names") — it does NOT actively
    cancel a populated `allow` list; a *specific* tool name in `deny` always does. See
    `policy_sdk.permissions.effective_tool_set`'s docstring for the exact semantics and
    why (the naive "`*` always means literally everything" reading would make the spec
    §12 example policy deny every tool it just allowed).

    Effective access = platform ∩ tenant ∩ agent ∩ mission (spec §12). A specific
    tool's deny always wins over that same scope's allow.
    """

    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=lambda: ["*"])

    @classmethod
    def allow_only(cls, tools: list[ToolName]) -> "ToolPolicy":
        return cls(allow=[t.value for t in tools], deny=["*"])


class BudgetPolicy(BaseModel):
    """Matches spec §22 exactly."""

    max_model_cost_usd: float = 2.00
    max_model_calls: int = 6
    max_runtime_minutes: int = 10
    max_retries: int = 2
    max_output_tokens: int = 8000
