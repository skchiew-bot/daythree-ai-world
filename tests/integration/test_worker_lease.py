"""R0 (ADR-013 F5): two workers must never both execute (and bill) the same task, and a
crashed worker's task must still be recoverable once its lease expires.
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from common.db.models import AuditEvent, Task
from contracts.enums import TaskStatus
from contracts.model import ModelRequest
from contracts.policy import BudgetPolicy
from mission_engine.engine.lease import TaskLease, is_leased
from mission_engine.engine.mission_service import create_mission, start_mission
from mission_engine.engine.queue import TASK_QUEUE_KEY
from model_gateway.gateway import ModelGateway
from model_gateway.providers.mock import MockModelProvider
from worker.main import MAX_AUTO_REQUEUES, process_task, requeue_orphaned_running_tasks

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
    real_sessionmaker = async_sessionmaker(db_session.bind, expire_on_commit=False)
    sessions_opened = []

    def counting_sessionmaker():
        sessions_opened.append(1)
        return real_sessionmaker()

    results = await asyncio.gather(
        process_task(fake_redis, counting_sessionmaker, deps, task.id),
        process_task(fake_redis, counting_sessionmaker, deps, task.id),
    )

    assert sorted(results) == [False, True]  # one worker ran it, the other backed off
    assert provider.calls == 1
    # The loser backs off before it opens a DB session at all: only the lease holder touches
    # the database (each worker would otherwise open its own pooled connection).
    assert len(sessions_opened) == 1
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
async def test_a_task_that_keeps_coming_back_is_failed_after_the_requeue_cap(
    db_session, fake_redis, seeded, engine_deps
):
    """The sweep runs every few seconds, so a task that fails for a non-model reason on
    every recovery must not be re-run (and re-announced in the audit trail) forever. Here
    no worker ever runs it, so the counter can only advance if the sweep itself persists it."""
    task = await _running_task(db_session, seeded)
    sessionmaker = async_sessionmaker(db_session.bind, expire_on_commit=False)
    publisher = engine_deps.event_publisher

    for _ in range(MAX_AUTO_REQUEUES):
        assert await requeue_orphaned_running_tasks(fake_redis, sessionmaker, publisher) == 1
    await db_session.refresh(task)
    assert task.retry_count == MAX_AUTO_REQUEUES  # persisted by the sweep, not by a rolled-back worker

    assert await requeue_orphaned_running_tasks(fake_redis, sessionmaker, publisher) == 0
    await db_session.refresh(task)
    assert task.status == TaskStatus.failed.value
    assert await fake_redis.llen(TASK_QUEUE_KEY) == MAX_AUTO_REQUEUES  # nothing queued by the last sweep

    events = (
        await db_session.execute(select(AuditEvent).where(AuditEvent.task_id == task.id))
    ).scalars().all()
    failed = [e for e in events if e.event_type == "task.failed"]
    assert len(failed) == 1 and failed[0].payload["data"] == {"reason": "max_requeues"}  # no free text
    assert any(e.event_type == "mission.failed" for e in events)


@pytest.mark.asyncio
async def test_a_sweep_recovery_counts_as_one_retry_not_two(db_session, fake_redis, seeded, engine_deps):
    task = await _running_task(db_session, seeded)
    sessionmaker = async_sessionmaker(db_session.bind, expire_on_commit=False)
    await requeue_orphaned_running_tasks(fake_redis, sessionmaker, engine_deps.event_publisher)

    await process_task(fake_redis, sessionmaker, engine_deps, task.id)

    await db_session.refresh(task)
    assert task.status == TaskStatus.completed.value
    assert task.retry_count == 1  # the sweep's bump; the executor must not add a second one


@pytest.mark.asyncio
async def test_a_failed_lease_release_does_not_crash_the_worker_loop(
    db_session, fake_redis, seeded, engine_deps
):
    task = await _running_task(db_session, seeded)
    sessionmaker = async_sessionmaker(db_session.bind, expire_on_commit=False)

    class _BrokenRedis:
        """acquire() works (delegated); refresh and release, which use a pipeline, blow up."""

        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def pipeline(self, *args, **kwargs):
            raise ConnectionError("redis went away")

    result = await process_task(_BrokenRedis(fake_redis), sessionmaker, engine_deps, task.id)

    assert result is True  # the error was logged, not raised into the worker loop
    await db_session.refresh(task)
    assert task.status == TaskStatus.completed.value
    assert await is_leased(fake_redis, task.id) is True  # left to expire by its TTL
