"""Worker entrypoint. Re-queues any task left in `running` status by a prior process that
died mid-execution (spec §15 "worker crash during model call" and success criterion 10
"runtime can restart without losing the mission") — the task_executor then resumes it from
its last checkpoint instead of starting over.

R0 (ADR-013 F5): a worker executes a task only while it holds that task's Redis lease
(`mission_engine.engine.lease`), and the orphan sweep skips tasks whose lease is live. The
sweep runs at startup and then every `ORPHAN_SWEEP_INTERVAL_SECONDS`, because a crashed
worker's lease outlives the crash by up to its TTL: a sweep at startup alone would skip the
task and never look again.
"""
from __future__ import annotations

import asyncio
import signal
import time

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from common.config import get_settings
from common.db.models import Task
from common.db.session import get_sessionmaker
from contracts.enums import TaskStatus
from contracts.ids import EntityId
from mission_engine.engine.lease import LeaseLostError, TaskLease, is_leased
from mission_engine.engine.queue import dequeue_task, enqueue_task
from mission_engine.engine.task_executor import EngineDeps, execute_task

from worker.deps import build_engine_deps, build_redis_client

logger = structlog.get_logger(__name__)

ORPHAN_SWEEP_INTERVAL_SECONDS = 10.0
# Every recovery of a task bumps `retry_count` and writes audit events. The sweep runs every
# few seconds, so a task that fails for a non-model reason on each recovery (an object-store
# outage, say) must stop being requeued automatically after this many tries; it then stays
# `running` for an operator, as it did before the periodic sweep existed.
MAX_AUTO_REQUEUES = 10
EXECUTABLE_STATUSES = frozenset({TaskStatus.queued.value, TaskStatus.running.value})


async def requeue_orphaned_running_tasks(redis_client, sessionmaker: async_sessionmaker | None = None) -> int:
    """Requeues `running` tasks that no live worker holds a lease on."""
    sessionmaker = sessionmaker or get_sessionmaker()
    async with sessionmaker() as session:
        result = await session.execute(
            select(Task.id).where(
                Task.status == TaskStatus.running.value, Task.retry_count < MAX_AUTO_REQUEUES
            )
        )
        running_ids = [row[0] for row in result.all()]

    requeued = 0
    for task_id in running_ids:
        if await is_leased(redis_client, task_id):
            continue  # another worker is executing it right now
        await enqueue_task(redis_client, task_id)
        logger.info("requeued_orphaned_task", task_id=str(task_id))
        requeued += 1
    return requeued


async def process_task(
    redis_client, sessionmaker: async_sessionmaker, deps: EngineDeps, task_id: EntityId
) -> bool:
    """Executes one dequeued task if (and only while) this worker holds its lease.
    Returns False when the task was skipped: leased by another worker, or already
    finished (a duplicate queue entry)."""
    lease = TaskLease(redis_client, task_id)
    if not await lease.acquire():
        logger.info("task_lease_held_elsewhere", task_id=str(task_id))
        return False
    try:
        async with sessionmaker() as session:
            task = await session.get(Task, task_id)
            if task is None or task.status not in EXECUTABLE_STATUSES:
                logger.info("task_not_executable", task_id=str(task_id))
                return False
            try:
                await lease.run(execute_task(session, deps, task_id))
                await session.commit()
            except LeaseLostError:
                await session.rollback()
                logger.error("task_lease_lost", task_id=str(task_id))
            except Exception:
                await session.rollback()
                logger.exception("task_execution_failed", task_id=str(task_id))
        return True
    finally:
        try:
            await lease.release()
        except Exception:  # noqa: BLE001 - the lease expires by TTL anyway; never crash the worker loop over it
            logger.exception("task_lease_release_failed", task_id=str(task_id))


async def run_forever() -> None:
    settings = get_settings()
    settings.require_safe_for_production()
    deps = build_engine_deps(settings)
    redis_client = build_redis_client(settings)
    sessionmaker = get_sessionmaker()

    requeued = await requeue_orphaned_running_tasks(redis_client)
    logger.info("worker_started", requeued_orphaned_tasks=requeued)
    last_sweep = time.monotonic()

    stop_event = asyncio.Event()

    def _handle_signal(*_args) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except NotImplementedError:
            pass  # Windows: signal handlers for SIGTERM aren't supported in the event loop

    while not stop_event.is_set():
        if time.monotonic() - last_sweep >= ORPHAN_SWEEP_INTERVAL_SECONDS:
            last_sweep = time.monotonic()
            try:
                await requeue_orphaned_running_tasks(redis_client)
            except Exception:
                logger.exception("orphan_sweep_failed")
        try:
            task_id = await dequeue_task(redis_client, timeout_seconds=5)
        except Exception:
            # A transient Redis hiccup here must not crash the whole process — that
            # would discard in-memory loop state for no reason now that the queue
            # client itself no longer races its own blocking timeout (see
            # `worker.deps.build_redis_client`). Log and retry the poll.
            logger.exception("dequeue_failed")
            await asyncio.sleep(1)
            continue
        if task_id is None:
            continue

        try:
            await process_task(redis_client, sessionmaker, deps, task_id)
        except Exception:
            # Redis or the DB failed around the lease or the task lookup, before or after
            # the work itself. The task was already popped from the queue, so put it back
            # (a duplicate entry is harmless: `process_task` skips finished or leased tasks).
            logger.exception("process_task_failed", task_id=str(task_id))
            await asyncio.sleep(1)
            try:
                await enqueue_task(redis_client, task_id)
            except Exception:
                logger.exception("requeue_after_failure_failed", task_id=str(task_id))


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
