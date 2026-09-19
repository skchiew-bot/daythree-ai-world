"""R0 (ADR-013 F5): the orphan sweep must not requeue a task another worker holds a lease
on. The old behaviour (requeue every `running` task) is what let a restarted second worker
re-run, and re-bill, a task a live worker was mid-call on.

Deliberately calls only `requeue_orphaned_running_tasks(redis_client)` with the sessionmaker
patched in, so the same tests run (and fail for a behavioural reason, not an import or
signature error) against the pre-lease implementation.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from contracts.enums import TaskStatus
from contracts.policy import BudgetPolicy
from mission_engine.engine.lease import TaskLease
from mission_engine.engine.mission_service import create_mission, start_mission
from mission_engine.engine.queue import TASK_QUEUE_KEY
from worker import main as worker_main

pytestmark = pytest.mark.integration


async def _running_task(db_session, seeded, monkeypatch):
    mission = await create_mission(
        db_session, tenant_id=seeded["tenant"].id, mission_code="MSN-SWEEP", title="Sweep", objective="x",
        requested_by=None, assigned_agent_id=seeded["agent"].id, budget_policy=BudgetPolicy(),
    )
    await db_session.commit()
    started = await start_mission(db_session, mission_id=mission.id)
    started.task.status = TaskStatus.running.value
    await db_session.commit()
    sessionmaker = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(worker_main, "get_sessionmaker", lambda: sessionmaker)
    return started.task


@pytest.mark.asyncio
async def test_orphan_requeue_skips_a_task_whose_lease_is_live(db_session, fake_redis, seeded, monkeypatch):
    task = await _running_task(db_session, seeded, monkeypatch)
    await TaskLease(fake_redis, task.id).acquire()  # another worker is mid-call on it

    assert await worker_main.requeue_orphaned_running_tasks(fake_redis) == 0
    assert await fake_redis.llen(TASK_QUEUE_KEY) == 0


@pytest.mark.asyncio
async def test_orphan_requeue_recovers_a_task_once_its_lease_has_expired(
    db_session, fake_redis, seeded, monkeypatch
):
    task = await _running_task(db_session, seeded, monkeypatch)
    await TaskLease(fake_redis, task.id, ttl_ms=50).acquire()  # holder crashed; nobody refreshes it
    assert await worker_main.requeue_orphaned_running_tasks(fake_redis) == 0

    await asyncio.sleep(0.1)

    assert await worker_main.requeue_orphaned_running_tasks(fake_redis) == 1
    assert await fake_redis.llen(TASK_QUEUE_KEY) == 1


@pytest.mark.asyncio
async def test_orphan_requeue_recovers_a_running_task_with_no_lease_at_all(
    db_session, fake_redis, seeded, monkeypatch
):
    await _running_task(db_session, seeded, monkeypatch)

    assert await worker_main.requeue_orphaned_running_tasks(fake_redis) == 1
