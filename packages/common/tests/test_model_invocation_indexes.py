"""R0 (ADR-013): the model declares the lookup indexes, so a fresh database (built by
`Base.metadata.create_all`) gets them too, not only databases that ran migration 0003b."""
import pytest

from common.db.models import ModelInvocation

pytestmark = pytest.mark.unit


def _indexes_by_name() -> dict[str, list[str]]:
    return {ix.name: [c.name for c in ix.columns] for ix in ModelInvocation.__table__.indexes}


def test_per_task_usage_lookup_is_indexed():
    assert _indexes_by_name()["ix_model_invocations_task_id"] == ["task_id"]


def test_per_tenant_agent_time_lookup_is_indexed():
    assert _indexes_by_name()["ix_model_invocations_tenant_agent_created"] == [
        "tenant_id", "agent_id", "created_at",
    ]
