"""Budget evaluator (spec §22). Checked before every model invocation — never after."""
from __future__ import annotations

from dataclasses import dataclass

from contracts.policy import BudgetPolicy


@dataclass(frozen=True)
class BudgetUsage:
    """Running totals for one task, as tracked by the Mission Engine."""

    calls_made: int = 0
    cost_spent_usd: float = 0.0
    elapsed_minutes: float = 0.0
    retries_made: int = 0


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    reason: str | None = None


def evaluate_budget(
    policy: BudgetPolicy,
    usage: BudgetUsage,
    *,
    requested_output_tokens: int,
    is_retry: bool = False,
) -> BudgetDecision:
    """Every check is a hard ceiling — none of them "round up" or grant slack, per
    spec §4 rule 15 (no silent fallback): a task that would exceed budget is rejected
    outright, not throttled or partially served.
    """
    if usage.calls_made >= policy.max_model_calls:
        return BudgetDecision(False, f"max_model_calls ({policy.max_model_calls}) reached.")

    if usage.cost_spent_usd >= policy.max_model_cost_usd:
        return BudgetDecision(
            False, f"max_model_cost_usd (${policy.max_model_cost_usd:.2f}) reached."
        )

    if usage.elapsed_minutes >= policy.max_runtime_minutes:
        return BudgetDecision(
            False, f"max_runtime_minutes ({policy.max_runtime_minutes}) exceeded."
        )

    if requested_output_tokens > policy.max_output_tokens:
        return BudgetDecision(
            False,
            f"requested_output_tokens ({requested_output_tokens}) exceeds "
            f"max_output_tokens ({policy.max_output_tokens}).",
        )

    if is_retry and usage.retries_made >= policy.max_retries:
        return BudgetDecision(False, f"max_retries ({policy.max_retries}) reached.")

    return BudgetDecision(True)
