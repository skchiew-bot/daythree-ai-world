"""The core walking-skeleton proof: create agent -> create mission -> start -> execute
-> artifact -> events -> audit timeline, against a real Postgres (spec §27
Integration Tests: "mission -> task -> artifact", "audit event persistence").
Requires Docker (testcontainers); skipped with a reason if unavailable — see
`tests/conftest.py`.
"""
from __future__ import annotations

import json

import pytest

from contracts.enums import EventType, TaskStatus
from contracts.policy import BudgetPolicy
from mission_engine.engine.mission_service import create_mission, start_mission
from mission_engine.engine.queue import dequeue_task, enqueue_task
from mission_engine.engine.task_executor import execute_task

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_full_mission_lifecycle_tc_p0_001_003_004_011(db_session, fake_redis, seeded, engine_deps):
    tenant, agent = seeded["tenant"], seeded["agent"]

    mission = await create_mission(
        db_session, tenant_id=tenant.id, mission_code="MSN-TEST-001", title="Test mission",
        objective="Say hello.", requested_by=seeded["admin"].id, assigned_agent_id=agent.id,
        budget_policy=BudgetPolicy(),
    )
    await db_session.commit()
    assert mission.status == "draft"  # TC-P0-003: valid mission persists

    start_result = await start_mission(db_session, mission_id=mission.id)
    await db_session.commit()  # commit before enqueueing — see start_mission's docstring
    await enqueue_task(fake_redis, start_result.task.id)
    assert start_result.newly_started is True
    task = start_result.task
    assert task.status == TaskStatus.queued.value

    task_id = await dequeue_task(fake_redis, timeout_seconds=1)
    assert task_id == task.id

    deps = engine_deps
    await execute_task(db_session, deps, task_id)
    await db_session.commit()

    await db_session.refresh(mission)
    await db_session.refresh(task)
    assert mission.status == "completed"  # TC-P0-004
    assert task.status == TaskStatus.completed.value
    assert task.output_artifact_id is not None  # TC-P0-004: artifact generated

    from sqlalchemy import select

    from common.db.models import Artifact, ModelInvocation

    artifact = (
        await db_session.execute(select(Artifact).where(Artifact.id == task.output_artifact_id))
    ).scalar_one()
    # TC-P0-011: artifact traces back to mission/task/agent/version/model invocation
    assert artifact.mission_id == mission.id
    assert artifact.task_id == task.id
    assert artifact.agent_id == agent.id
    assert artifact.agent_version_id == agent.active_version_id
    json.loads(await deps.object_store.get_object(artifact.storage_uri.removeprefix("s3://test-bucket/")))

    invocation = (
        await db_session.execute(select(ModelInvocation).where(ModelInvocation.task_id == task.id))
    ).scalar_one()
    assert invocation.provider == "mock"  # TC-P0-004: model telemetry stored


@pytest.mark.asyncio
async def test_duplicate_start_request_creates_only_one_run_tc_p0_010(db_session, fake_redis, seeded):
    mission = await create_mission(
        db_session, tenant_id=seeded["tenant"].id, mission_code="MSN-TEST-DUP", title="Dup test",
        objective="x", requested_by=None, assigned_agent_id=seeded["agent"].id, budget_policy=BudgetPolicy(),
    )
    await db_session.commit()

    first = await start_mission(db_session, mission_id=mission.id)
    await db_session.commit()
    second = await start_mission(db_session, mission_id=mission.id)
    await db_session.commit()

    assert first.newly_started is True
    assert second.newly_started is False
    assert first.task.id == second.task.id

    from sqlalchemy import func, select

    from common.db.models import Task

    count = (
        await db_session.execute(select(func.count()).select_from(Task).where(Task.mission_id == mission.id))
    ).scalar_one()
    assert count == 1  # only one task/run ever created


@pytest.mark.asyncio
async def test_audit_timeline_reconstructs_full_lifecycle_tc_p0_013(db_session, fake_redis, seeded, engine_deps):
    mission = await create_mission(
        db_session, tenant_id=seeded["tenant"].id, mission_code="MSN-TEST-AUDIT", title="Audit test",
        objective="x", requested_by=None, assigned_agent_id=seeded["agent"].id, budget_policy=BudgetPolicy(),
    )
    await db_session.commit()
    audit_start_result = await start_mission(db_session, mission_id=mission.id)
    await db_session.commit()
    await enqueue_task(fake_redis, audit_start_result.task.id)

    task_id = await dequeue_task(fake_redis, timeout_seconds=1)
    await execute_task(db_session, engine_deps, task_id)
    await db_session.commit()

    from sqlalchemy import select

    from common.db.models import AuditEvent

    events = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.mission_id == mission.id).order_by(AuditEvent.occurred_at.asc())
        )
    ).scalars().all()
    event_types = [e.event_type for e in events]

    assert event_types[0] == EventType.task_started.value
    assert EventType.model_requested.value in event_types
    assert EventType.model_completed.value in event_types
    assert EventType.artifact_created.value in event_types
    assert event_types[-2] == EventType.task_completed.value
    assert event_types[-1] == EventType.mission_completed.value
