"""R0 (ADR-013 F5): a worker may execute a task only while it holds that task's lease."""
import asyncio

import fakeredis.aioredis
import pytest

from contracts.ids import new_id
from mission_engine.engine.lease import LeaseLostError, TaskLease, is_leased

pytestmark = pytest.mark.unit


@pytest.fixture
def redis_client():
    return fakeredis.aioredis.FakeRedis()


@pytest.mark.asyncio
async def test_only_one_holder_can_acquire(redis_client):
    task_id = new_id()
    first, second = TaskLease(redis_client, task_id), TaskLease(redis_client, task_id)

    assert await first.acquire() is True
    assert await second.acquire() is False
    assert await is_leased(redis_client, task_id) is True


@pytest.mark.asyncio
async def test_release_frees_the_lease_for_the_next_holder(redis_client):
    task_id = new_id()
    first, second = TaskLease(redis_client, task_id), TaskLease(redis_client, task_id)
    await first.acquire()
    await first.release()

    assert await is_leased(redis_client, task_id) is False
    assert await second.acquire() is True


@pytest.mark.asyncio
async def test_release_never_deletes_someone_elses_lease(redis_client):
    task_id = new_id()
    stale, current = TaskLease(redis_client, task_id, ttl_ms=50), TaskLease(redis_client, task_id)
    await stale.acquire()
    await asyncio.sleep(0.1)  # stale's lease expires (its worker was slow/crashed)
    assert await current.acquire() is True

    await stale.release()  # must be a no-op: the token no longer matches

    assert await is_leased(redis_client, task_id) is True
    assert await stale.refresh() is False


@pytest.mark.asyncio
async def test_a_crashed_holders_lease_expires_so_the_task_is_recoverable(redis_client):
    task_id = new_id()
    crashed = TaskLease(redis_client, task_id, ttl_ms=50)
    await crashed.acquire()  # ...and never refreshed or released: the worker died
    await asyncio.sleep(0.1)

    assert await is_leased(redis_client, task_id) is False
    assert await TaskLease(redis_client, task_id).acquire() is True


@pytest.mark.asyncio
async def test_refresh_extends_a_live_lease(redis_client):
    task_id = new_id()
    lease = TaskLease(redis_client, task_id, ttl_ms=200)
    await lease.acquire()
    await asyncio.sleep(0.12)
    assert await lease.refresh() is True
    await asyncio.sleep(0.12)  # past the original expiry, inside the refreshed one

    assert await is_leased(redis_client, task_id) is True


@pytest.mark.asyncio
async def test_run_keeps_the_lease_alive_while_work_outlasts_the_ttl(redis_client):
    task_id = new_id()
    lease = TaskLease(redis_client, task_id, ttl_ms=200, refresh_seconds=0.05)
    await lease.acquire()

    async def slow_work():
        await asyncio.sleep(0.5)
        return "done"

    assert await lease.run(slow_work()) == "done"
    assert await is_leased(redis_client, task_id) is True  # still ours until release()
    await lease.release()
    assert await is_leased(redis_client, task_id) is False


@pytest.mark.asyncio
async def test_run_cancels_the_work_and_raises_when_the_lease_is_lost(redis_client):
    task_id = new_id()
    lease = TaskLease(redis_client, task_id, ttl_ms=5_000, refresh_seconds=0.05)
    await lease.acquire()
    finished = False

    async def slow_work():
        nonlocal finished
        await asyncio.sleep(2)
        finished = True

    async def steal_the_lease():
        await asyncio.sleep(0.1)
        await redis_client.set(f"daythree:task_lease:{task_id}", "someone-else")

    stealer = asyncio.ensure_future(steal_the_lease())
    with pytest.raises(LeaseLostError):
        await lease.run(slow_work())
    await stealer
    assert finished is False
