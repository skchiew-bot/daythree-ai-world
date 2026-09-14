"""Worker entrypoint. On startup, re-queues any task left in `running` status by a
prior process that died mid-execution (spec §15 "worker crash during model call" and
success criterion 10 "runtime can restart without losing the mission") — the
task_executor then resumes it from its last checkpoint instead of starting over.
"""
from __future__ import annotations

import asyncio
import signal

import structlog
from sqlalchemy import select

from common.config import get_settings
from common.db.models import Task
from common.db.session import get_sessionmaker
from contracts.enums import TaskStatus
from mission_engine.engine.queue import dequeue_task, enqueue_task
from mission_engine.engine.task_executor import execute_task

from worker.deps import build_engine_deps, build_redis_client

logger = structlog.get_logger(__name__)


async def requeue_orphaned_running_tasks(redis_client) -> int:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        result = await session.execute(select(Task.id).where(Task.status == TaskStatus.running.value))
        orphaned_ids = [row[0] for row in result.all()]

    for task_id in orphaned_ids:
        await enqueue_task(redis_client, task_id)
        logger.info("requeued_orphaned_task", task_id=str(task_id))
    return len(orphaned_ids)


async def run_forever() -> None:
    settings = get_settings()
    settings.require_safe_for_production()
    deps = build_engine_deps(settings)
    redis_client = build_redis_client(settings)
    sessionmaker = get_sessionmaker()

    requeued = await requeue_orphaned_running_tasks(redis_client)
    logger.info("worker_started", requeued_orphaned_tasks=requeued)

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

        async with sessionmaker() as session:
            try:
                await execute_task(session, deps, task_id)
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("task_execution_failed", task_id=str(task_id))


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
