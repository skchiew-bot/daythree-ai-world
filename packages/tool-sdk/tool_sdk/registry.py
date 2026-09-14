"""Dispatches a tool-by-name call after checking permission — the single choke point
every tool invocation passes through (spec §12: deny-by-default, every external side
effect requires an explicit tool permission).
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Optional

from contracts.policy import ToolPolicy
from policy_sdk.permissions import PermissionDecision, evaluate_tool_access
from tool_sdk.tools import DEFAULT_TOOL_HANDLERS, ToolContext, ToolHandler


@dataclass
class ToolExecutionResult:
    tool: str
    decision: PermissionDecision
    output: Optional[dict[str, Any]] = None
    error: Optional[str] = None

    @property
    def executed(self) -> bool:
        return self.decision.allowed and self.error is None


@dataclass
class ToolRegistry:
    handlers: dict[str, ToolHandler] = field(default_factory=lambda: dict(DEFAULT_TOOL_HANDLERS))

    async def execute(
        self,
        tool: str,
        params: dict[str, Any],
        context: ToolContext,
        *,
        platform_policy: ToolPolicy,
        tenant_policy: ToolPolicy,
        agent_policy: ToolPolicy,
        mission_policy: Optional[ToolPolicy] = None,
    ) -> ToolExecutionResult:
        decision = evaluate_tool_access(
            tool,
            platform_policy=platform_policy,
            tenant_policy=tenant_policy,
            agent_policy=agent_policy,
            mission_policy=mission_policy,
        )
        if not decision.allowed:
            return ToolExecutionResult(tool=tool, decision=decision)

        handler = self.handlers.get(tool)
        if handler is None:
            return ToolExecutionResult(
                tool=tool, decision=decision, error=f"No handler registered for tool '{tool}'."
            )

        try:
            result = handler(params, context)
            if inspect.isawaitable(result):
                result = await result
            return ToolExecutionResult(tool=tool, decision=decision, output=result)
        except Exception as exc:  # noqa: BLE001 — surfaced as a typed tool.failed event upstream
            return ToolExecutionResult(tool=tool, decision=decision, error=str(exc))
