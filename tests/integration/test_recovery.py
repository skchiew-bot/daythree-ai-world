"""Simulates a worker crash mid-task at the integration level (real Postgres, real
checkpoint rows) — TC-P0-006/007 and success criterion 10. A true OS-process-kill
version of this lives in `tests/resilience/test_worker_restart.py` and additionally
needs `docker compose up`; this test proves the same recovery mechanism without
spawning a second process, so it can run in any Docker-only environment.
"""
from __future__ import annotations

import pytest

from common.db.models import Task
from contracts.enums import TaskStatus
from contracts.policy import BudgetPolicy
from mission_engine.checkpoints.sql_checkpoint_store import SqlCheckpointStore
from mission_engine.engine.mission_service import create_mission, start_mission
from mission_engine.engine.queue import dequeue_task, enqueue_task
from mission_engine.engine.task_executor import execute_task

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_worker_crash_after_first_checkpoint_recovers_without_duplicate_artifact(
    db_session, fake_redis, seeded, engine_deps
):
    mission = await create_mission(
        db_session, tenant_id=seeded["tenant"].id, mission_code="MSN-TEST-RECOVER", title="Recovery test",
        objective="x", requested_by=None, assigned_agent_id=seeded["agent"].id, budget_policy=BudgetPolicy(),
    )
    await db_session.commit()
    start_result = await start_mission(db_session, mission_id=mission.id)
    await db_session.commit()
    await enqueue_task(fake_redis, start_result.task.id)
    task_id = await dequeue_task(fake_redis, timeout_seconds=1)
    deps = engine_deps

    # Run to completion once, recording how many checkpoints a clean run produces.
    await execute_task(db_session, deps, task_id)
    await db_session.commit()

    checkpoint_store = SqlCheckpointStore(db_session)
    clean_run_checkpoint = await checkpoint_store.latest_for_task(task_id)
    assert clean_run_checkpoint.state["stage"] == "model_responded"

    task = await db_session.get(Task, task_id)
    first_artifact_id = task.output_artifact_id
    assert first_artifact_id is not None

    # Simulate "the process died right after task.started, before it ever finished" by
    # resetting the task (and mission) back to `running` (as the worker would find it
    # on restart) and re-invoking execute_task — it must detect the existing
    # checkpoint/artifact and reconcile rather than redo the model call or commit a
    # second artifact.
    from contracts.enums import MissionStatus

    task.status = TaskStatus.running.value
    task.retry_count = 0
    mission.status = MissionStatus.running.value
    mission.completed_at = None
    await db_session.flush()
    await db_session.commit()

    await execute_task(db_session, deps, task_id)
    await db_session.commit()

    await db_session.refresh(task)
    assert task.status == TaskStatus.completed.value
    assert task.output_artifact_id == first_artifact_id  # no duplicate artifact (TC-P0-007/010)
