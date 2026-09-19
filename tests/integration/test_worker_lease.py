"""R0 (ADR-013 F5): two workers must never both execute (and bill) the same task, and a
crashed worker's task must still be recoverable once its lease expires.
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from common.db.models import Task
from contracts.enums import TaskStatus
from contracts.model import ModelRequest
from contracts.policy import BudgetPolicy
from mission_engine.engine.lease import TaskLease
from mission_engine.engine.mission_service import create_mission, start_mission
from mission_engine.engine.queue import TASK_QUEUE_KEY
from model_gateway.gateway import ModelGateway
from model_gateway.providers.mock import MockModelProvider
from worker.main import process_task, requeue_orphaned_running_tasks

pytestmark = pytest.mark.integration


class SlowCountingProvider:
    """Counts provider calls and stays 'in flight' long enough for a second worker to race."""

    def __init__(self, delay_seconds: float = 0.3):
        self.calls = 0
        self._delay = delay_seconds
        self._inner = MockModelProvider()

    async def generate(self, request: ModelRequest):
        self.calls += 1
        await asyncio.sleep(self._delay)
        return await self._inner.generate(request)


async def _running_task(db_session, seeded) -> Task:
    mission = await create_mission(
        db_session, tenant_id=seeded["tenant"].id, mission_code="MSN-LEASE", title="Lease", objective="x",
        requested_by=None, assigned_agent_id=seeded["agent"].id, budget_policy=BudgetPolicy(),
    )
    await db_session.commit()
    started = await start_mission(db_session, mission_id=mission.id)
    started.task.status = TaskStatus.running.value  # what a worker that died mid-task leaves behind
    await db_session.commit()
    return started.task


@pytest.mark.asyncio
async def test_two_workers_and_one_running_task_make_exactly_one_provider_call(
    db_session, fake_redis, seeded, engine_deps
):
    task = await _running_task(db_session, seeded)
    provider = SlowCountingProvider()
    deps = dataclasses.replace(engine_deps, model_gateway=ModelGateway(providers={"mock": provider}))
    sessionmaker = async_sessionmaker(db_session.bind, expire_on_commit=False)

    results = await asyncio.gather(
        process_task(fake_redis, sessionmaker, deps, task.id),
        process_task(fake_redis, sessionmaker, deps, task.id),
    )

    assert sorted(results) == [False, True]  # one worker ran it, the other backed off
    assert provider.calls == 1
    await db_session.refresh(task)
    assert task.status == TaskStatus.completed.value


@pytest.mark.asyncio
async def test_a_duplicate_queue_entry_for_a_finished_task_is_ignored(
    db_session, fake_redis, seeded, engine_deps
):
    task = await _running_task(db_session, seeded)
    provider = SlowCountingProvider(delay_seconds=0)
    deps = dataclasses.replace(engine_deps, model_gateway=ModelGateway(providers={"mock": provider}))
    sessionmaker = async_sessionmaker(db_session.bind, expire_on_commit=False)

    assert await process_task(fake_redis, sessionmaker, deps, task.id) is True
    assert await process_task(fake_redis, sessionmaker, deps, task.id) is False  # already completed

    assert provider.calls == 1


@pytest.mark.asyncio
async def test_the_lease_is_released_after_the_task_finishes(db_session, fake_redis, seeded, engine_deps):
    task = await _running_task(db_session, seeded)
    sessionmaker = async_sessionmaker(db_session.bind, expire_on_commit=False)
    await process_task(fake_redis, sessionmaker, engine_deps, task.id)

    assert await TaskLease(fake_redis, task.id).acquire() is True


@pytest.mark.asyncio
async def test_orphan_requeue_skips_a_task_whose_lease_is_live(db_session, fake_redis, seeded):
    task = await _running_task(db_session, seeded)
    sessionmaker = async_sessionmaker(db_session.bind, expire_on_commit=False)
    await TaskLease(fake_redis, task.id).acquire()  # another worker is mid-call on it

    assert await requeue_orphaned_running_tasks(fake_redis, sessionmaker) == 0
    assert await fake_redis.llen(TASK_QUEUE_KEY) == 0


@pytest.mark.asyncio
async def test_orphan_requeue_recovers_a_task_once_its_lease_has_expired(db_session, fake_redis, seeded):
    task = await _running_task(db_session, seeded)
    sessionmaker = async_sessionmaker(db_session.bind, expire_on_commit=False)
    await TaskLease(fake_redis, task.id, ttl_ms=50).acquire()  # holder crashed; nobody refreshes it
    assert await requeue_orphaned_running_tasks(fake_redis, sessionmaker) == 0

    await asyncio.sleep(0.1)

    assert await requeue_orphaned_running_tasks(fake_redis, sessionmaker) == 1
    assert await fake_redis.llen(TASK_QUEUE_KEY) == 1


@pytest.mark.asyncio
async def test_orphan_requeue_recovers_a_running_task_with_no_lease_at_all(db_session, fake_redis, seeded):
    await _running_task(db_session, seeded)
    sessionmaker = async_sessionmaker(db_session.bind, expire_on_commit=False)

    assert await requeue_orphaned_running_tasks(fake_redis, sessionmaker) == 1
