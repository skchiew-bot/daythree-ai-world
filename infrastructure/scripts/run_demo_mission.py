"""Runs the exact Phase 0 demonstration mission from spec §19 end-to-end and prints
the resulting artifact plus the full audit timeline — this is the script a reviewer
runs to see success criteria 1-14 actually hold, not just described.

Works whether or not a separate `worker` process/container is already running: it
enqueues the task, tries briefly to claim it itself (so `make demo` works with just
`docker compose up -d postgres redis minio` and no worker), and falls back to polling
the DB if some other worker claimed it first.
"""
from __future__ import annotations

import asyncio
import json

import structlog
from sqlalchemy import select

from common.config import get_settings
from common.db.models import Agent, Artifact, AuditEvent, Mission, Tenant
from common.db.session import get_sessionmaker
from contracts.enums import MissionStatus, TaskStatus
from contracts.ids import new_id
from contracts.policy import BudgetPolicy

from mission_engine.engine.mission_service import create_mission, start_mission
from mission_engine.engine.queue import dequeue_task
from mission_engine.engine.task_executor import execute_task
from worker.deps import build_engine_deps, build_redis_client

logger = structlog.get_logger(__name__)

DEMO_MISSION_CODE = "MSN-DEMO-PHASE0"
DEMO_TITLE = "Research the requirements for an AI-powered repeated-interaction analysis capability"
DEMO_OBJECTIVE = (
    "Produce a concise business and technical requirement note explaining what data, "
    "integrations, controls, KPIs, and risks should be considered when analyzing "
    "repeated customer interactions across voice and digital channels."
)


async def run_demo() -> None:
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    redis_client = build_redis_client(settings)

    async with sessionmaker() as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.code == settings.seed_tenant_code))).scalar_one()
        atlas = (await session.execute(select(Agent).where(Agent.tenant_id == tenant.id, Agent.agent_code == "AGT-000001"))).scalar_one()

        mission = (
            await session.execute(select(Mission).where(Mission.mission_code == DEMO_MISSION_CODE))
        ).scalar_one_or_none()
        if mission is None:
            mission = await create_mission(
                session, tenant_id=tenant.id, mission_code=DEMO_MISSION_CODE, title=DEMO_TITLE,
                objective=DEMO_OBJECTIVE, requested_by=None, assigned_agent_id=atlas.id,
                budget_policy=BudgetPolicy(),
            )
            await session.commit()
            logger.info("demo_mission_created", mission_id=str(mission.id))

        if mission.status in (MissionStatus.draft.value, MissionStatus.ready.value):
            result = await start_mission(session, redis_client, mission_id=mission.id)
            await session.commit()
            logger.info("demo_mission_started", newly_started=result.newly_started)

    # Try to claim and run the task ourselves first (works with no separate worker).
    task_id = await dequeue_task(redis_client, timeout_seconds=3)
    deps = build_engine_deps(settings)
    if task_id is not None:
        async with sessionmaker() as session:
            await execute_task(session, deps, task_id)
            await session.commit()
        logger.info("demo_task_executed_inline", task_id=str(task_id))
    else:
        logger.info("demo_task_claimed_by_another_worker_polling_for_completion")
        for _ in range(60):
            async with sessionmaker() as session:
                mission = await session.get(Mission, mission.id)
                if mission.status in (MissionStatus.completed.value, MissionStatus.failed.value):
                    break
            await asyncio.sleep(1)

    async with sessionmaker() as session:
        mission = await session.get(Mission, mission.id)
        artifacts = (await session.execute(select(Artifact).where(Artifact.mission_id == mission.id))).scalars().all()
        timeline = (
            await session.execute(
                select(AuditEvent).where(AuditEvent.mission_id == mission.id).order_by(AuditEvent.occurred_at.asc())
            )
        ).scalars().all()

        print(f"\n=== Mission {mission.mission_code}: {mission.status} ===\n")
        for artifact in artifacts:
            obj = deps.object_store
            body = await obj.get_object(artifact.storage_uri.removeprefix(f"s3://{settings.object_store_bucket}/"))
            print(f"--- Artifact: {artifact.title} ({artifact.artifact_type}, v{artifact.version}) ---")
            try:
                print(json.dumps(json.loads(body), indent=2)[:2000])
            except json.JSONDecodeError:
                print(body.decode("utf-8", errors="replace")[:2000])
            print()

        print(f"--- Audit timeline ({len(timeline)} events) ---")
        for event in timeline:
            print(f"{event.occurred_at.isoformat()}  {event.event_type}")

    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(run_demo())
