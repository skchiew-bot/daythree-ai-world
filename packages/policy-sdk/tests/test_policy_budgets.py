"""Unit tests for the budget evaluator (spec §22, TC-P0-009)."""
import pytest

from contracts.policy import BudgetPolicy
from policy_sdk.budgets import BudgetUsage, evaluate_budget

pytestmark = pytest.mark.unit

POLICY = BudgetPolicy(
    max_model_cost_usd=2.00, max_model_calls=6, max_runtime_minutes=10,
    max_retries=2, max_output_tokens=8000,
)


def test_fresh_task_is_within_budget():
    decision = evaluate_budget(POLICY, BudgetUsage(), requested_output_tokens=1000)
    assert decision.allowed is True


def test_max_calls_exceeded_blocks_next_call_tc_p0_009():
    usage = BudgetUsage(calls_made=6)
    decision = evaluate_budget(POLICY, usage, requested_output_tokens=1000)
    assert decision.allowed is False
    assert "max_model_calls" in decision.reason


def test_max_cost_exceeded_blocks_next_call():
    usage = BudgetUsage(cost_spent_usd=2.00)
    decision = evaluate_budget(POLICY, usage, requested_output_tokens=1000)
    assert decision.allowed is False
    assert "max_model_cost_usd" in decision.reason


def test_max_runtime_exceeded_blocks_next_call():
    usage = BudgetUsage(elapsed_minutes=10.5)
    decision = evaluate_budget(POLICY, usage, requested_output_tokens=1000)
    assert decision.allowed is False
    assert "max_runtime_minutes" in decision.reason


def test_requested_output_tokens_over_ceiling_is_rejected():
    decision = evaluate_budget(POLICY, BudgetUsage(), requested_output_tokens=9000)
    assert decision.allowed is False
    assert "max_output_tokens" in decision.reason


def test_retry_beyond_max_retries_is_rejected():
    usage = BudgetUsage(retries_made=2)
    decision = evaluate_budget(POLICY, usage, requested_output_tokens=1000, is_retry=True)
    assert decision.allowed is False
    assert "max_retries" in decision.reason


def test_retry_within_limit_is_allowed():
    usage = BudgetUsage(retries_made=1)
    decision = evaluate_budget(POLICY, usage, requested_output_tokens=1000, is_retry=True)
    assert decision.allowed is True
