"""Tool permission evaluator (spec §12).

Effective access = platform ∩ tenant ∩ agent ∩ mission. Deny always wins. A tool that
isn't in ANY scope's allow list — including one that doesn't exist at all — is denied
by construction, not by a special case: `effective_tool_set` for a scope with
`allow=[]` is the empty set, and intersecting with the empty set is always empty.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from contracts.enums import ToolName
from contracts.policy import ToolPolicy

ALL_TOOLS: frozenset[str] = frozenset(t.value for t in ToolName)


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    tool: str
    denied_by_scope: Optional[str] = None
    reason: Optional[str] = None


def effective_tool_set(policy: ToolPolicy, universe: frozenset[str] = ALL_TOOLS) -> frozenset[str]:
    """The set of tools this single scope permits, before intersecting with other scopes.

    `"*"` in `deny` (the spec §12 example's `"deny": ["*"]`) documents "default-deny —
    nothing is allowed except what `allow` names"; it is NOT an active denial that would
    cancel out an explicit `allow` entry, otherwise the spec's own example policy would
    deny every tool it just allowed. A `"*"` elsewhere in `deny`, or any *specific* tool
    name in `deny`, always actively removes that tool regardless of `allow` — that's the
    "deny always wins" rule for real overrides (e.g. platform revoking one tool tenant-
    wide while still allowing `"*"` broadly).
    """
    allowed = universe if "*" in policy.allow else frozenset(policy.allow) & universe
    explicit_denies = (frozenset(policy.deny) - {"*"}) & universe
    return allowed - explicit_denies


def evaluate_tool_access(
    tool: str,
    *,
    platform_policy: ToolPolicy,
    tenant_policy: ToolPolicy,
    agent_policy: ToolPolicy,
    mission_policy: Optional[ToolPolicy] = None,
    universe: frozenset[str] = ALL_TOOLS,
) -> PermissionDecision:
    """Evaluate one tool against every applicable scope, in order, stopping at the
    first scope that doesn't permit it (so the decision can name which scope denied
    it — that detail goes straight into the `tool.denied` audit event).
    """
    scopes: list[tuple[str, ToolPolicy]] = [
        ("platform", platform_policy),
        ("tenant", tenant_policy),
        ("agent", agent_policy),
    ]
    if mission_policy is not None:
        scopes.append(("mission", mission_policy))

    if tool not in universe:
        return PermissionDecision(
            allowed=False, tool=tool, denied_by_scope=None,
            reason=f"'{tool}' is not a recognized Phase 0 tool.",
        )

    for scope_name, policy in scopes:
        if tool not in effective_tool_set(policy, universe):
            return PermissionDecision(
                allowed=False, tool=tool, denied_by_scope=scope_name,
                reason=f"Denied by {scope_name} tool policy.",
            )

    return PermissionDecision(allowed=True, tool=tool)


class PermissionDenied(Exception):
    def __init__(self, decision: PermissionDecision):
        self.decision = decision
        super().__init__(decision.reason)


def require_tool_access(tool: str, **kwargs) -> None:
    """Same as `evaluate_tool_access` but raises `PermissionDenied` on denial —
    convenient at the one call site (agent runtime, before invoking a tool) that must
    hard-stop execution rather than branch on a decision object.
    """
    decision = evaluate_tool_access(tool, **kwargs)
    if not decision.allowed:
        raise PermissionDenied(decision)
