"""Task execution — spec §13 steps 7-17, run by the worker for exactly one task per
call. Handles both a fresh task (no checkpoint yet) and a resumed one (a checkpoint
already exists because a previous attempt crashed mid-flight) through the same code
path: the runtime adapter decides internally whether to call the model again.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from agent_runtime.adapters.durable_adapter import DurableAgentRuntimeAdapter
from artifact_service.service import commit_artifact
from artifact_service.storage.object_store import ObjectStore
from common.db.models import Agent, AgentVersion, Mission, ModelPolicy, Task
from contracts.enums import (
    ActorType,
    ArtifactType,
    EventType,
    MissionStatus,
    TaskStatus,
)
from contracts.events import Actor, build_event
from contracts.ids import EntityId
from contracts.output_contract import validate_mission_output
from contracts.policy import BudgetPolicy, ToolPolicy
from contracts.runtime import RunContext
from event_service.publisher import EventPublisher
from model_gateway.gateway import BudgetExceededError, ModelGateway, ModelGatewayError

from mission_engine.checkpoints.sql_checkpoint_store import SqlCheckpointStore
from mission_engine.engine.usage import SqlUsageProvider

REPAIR_INSTRUCTION_TEMPLATE = (
    "\n\nYour previous answer was rejected by the output validator: {error}\n"
    "Re-answer now with a single corrected JSON object that matches the OUTPUT CONTRACT "
    "exactly. Do not include any text outside the JSON object."
)


@dataclass
class EngineDeps:
    model_gateway: ModelGateway
    object_store: ObjectStore
    event_publisher: EventPublisher


class TaskExecutionError(Exception):
    """Raised only for genuinely unexpected states (missing agent/version/policy row) —
    every *expected* failure path (budget exceeded, model failure, invalid output after
    repair) is handled inline and ends with the task/mission marked failed, not with
    an exception, per spec §4 rule 15 (no silent fallback, but also no crash-shaped
    handling for expected outcomes)."""


async def execute_task(session: AsyncSession, deps: EngineDeps, task_id: EntityId) -> None:
    attempt_started_at = datetime.now(timezone.utc)
    task = await session.get(Task, task_id)
    if task is None:
        raise TaskExecutionError(f"Task {task_id} does not exist.")
    mission = await session.get(Mission, task.mission_id)
    agent = await session.get(Agent, task.assigned_agent_id)
    if mission is None or agent is None or agent.active_version_id is None:
        raise TaskExecutionError(f"Task {task_id} has no resolvable mission/agent/active version.")
    agent_version = await session.get(AgentVersion, agent.active_version_id)
    model_policy = await session.get(ModelPolicy, agent_version.model_policy_id)

    correlation_id = mission.id
    actor = Actor(type=ActorType.agent, id=agent.id)

    checkpoint_store = SqlCheckpointStore(session)
    existing_checkpoint = await checkpoint_store.latest_for_task(task_id)
    is_resume = existing_checkpoint is not None

    # Whether this is the very first attempt is decided by `retry_count`/checkpoint
    # history, not `task.status` — a retried task is re-queued to `queued` by the
    # `/retry` endpoint just like a fresh one, so status alone can't distinguish them,
    # and a worker-restart resume must also count as a retry, not a fresh start.
    # `running` on entry means a worker died (or lost its lease) mid-task and the orphan
    # sweep recovered it; the sweep already counted that recovery in `retry_count` (and
    # persisted it, which is what caps automatic recoveries). `queued` is a fresh task or
    # an operator /retry.
    found_running = task.status == TaskStatus.running.value
    is_first_attempt = task.retry_count == 0 and existing_checkpoint is None and not found_running
    task.status = TaskStatus.running.value
    if is_first_attempt:
        task.started_at = func.now()
        await _publish(deps, session, EventType.task_started, mission, task, agent, correlation_id, actor)
    else:
        if not found_running:
            task.retry_count += 1
        await _publish(
            deps, session, EventType.task_retry_started, mission, task, agent, correlation_id, actor,
            data={"retry_count": task.retry_count},
        )
    await session.flush()

    tool_policy = ToolPolicy(**agent_version.tool_policy)
    budget_policy = BudgetPolicy(**task.budget_policy)
    context = RunContext(
        tenant_id=mission.tenant_id, mission_id=mission.id, task_id=task.id, agent_id=agent.id,
        agent_version_id=agent_version.id, correlation_id=correlation_id,
        system_prompt=agent_version.system_prompt, mission_objective=mission.objective,
        task_instructions=task.instructions, tool_policy=tool_policy, budget_policy=budget_policy,
        available_context=task.input_context or {},
        model_provider=model_policy.primary_provider, model_name=model_policy.primary_model,
    )
    adapter = DurableAgentRuntimeAdapter(
        model_gateway=deps.model_gateway, checkpoint_store=checkpoint_store,
        usage_provider=SqlUsageProvider(
            session, tenant_id=mission.tenant_id, mission_id=mission.id, task_id=task.id,
            agent_id=agent.id, attempt_started_at=attempt_started_at,
        ),
    )

    try:
        if is_resume:
            await _publish(deps, session, EventType.runtime_recovered, mission, task, agent, correlation_id, actor)
            if existing_checkpoint.state.get("stage") == "prompt_assembled":
                await _publish(deps, session, EventType.model_requested, mission, task, agent, correlation_id, actor)
            result = await adapter.resume(existing_checkpoint)
        else:
            handle = await adapter.initialize_run(context)
            await _publish(deps, session, EventType.model_requested, mission, task, agent, correlation_id, actor)
            result = await adapter.execute(handle)
    except BudgetExceededError as exc:
        await _publish(
            deps, session, EventType.budget_exceeded, mission, task, agent, correlation_id, actor,
            data={"reason": str(exc)},
        )
        await _fail(deps, session, mission, task, agent, correlation_id, actor, str(exc))
        return
    except ModelGatewayError as exc:
        await _publish(
            deps, session, EventType.model_failed, mission, task, agent, correlation_id, actor,
            data={"error": str(exc)},
        )
        await _fail(deps, session, mission, task, agent, correlation_id, actor, str(exc))
        return

    # The `model_invocations` rows for every attempt (failed ones included) were already
    # committed by the write-ahead ledger while the gateway ran; nothing is recorded here.
    if result.model_telemetry is not None:
        await _publish(
            deps, session, EventType.model_completed, mission, task, agent, correlation_id, actor,
            data=_model_completed_data(result.model_telemetry),
        )

    if result.final_checkpoint is not None:
        await _publish(
            deps, session, EventType.runtime_checkpoint_created, mission, task, agent, correlation_id, actor,
            data={"sequence": result.final_checkpoint.sequence},
        )

    # Durability boundary: the checkpoint itself was already committed inside the adapter
    # (see `SqlCheckpointStore.save`'s docstring) and so was the model_invocations charge
    # (write-ahead ledger); this commits the model.completed event just published.
    await session.commit()

    final_text = result.output_text
    parsed, error = validate_mission_output(final_text)

    if parsed is None:
        repair_context = context.model_copy(
            update={"task_instructions": context.task_instructions + REPAIR_INSTRUCTION_TEMPLATE.format(error=error)}
        )
        repair_handle = await adapter.initialize_run(repair_context)
        await _publish(deps, session, EventType.model_requested, mission, task, agent, correlation_id, actor,
                        data={"repair_attempt": True})
        try:
            repair_result = await adapter.execute(repair_handle)
        except (BudgetExceededError, ModelGatewayError) as exc:
            await _fail(deps, session, mission, task, agent, correlation_id, actor, f"repair attempt failed: {exc}")
            return

        if repair_result.model_telemetry is not None:
            await _publish(deps, session, EventType.model_completed, mission, task, agent, correlation_id, actor,
                            data={**_model_completed_data(repair_result.model_telemetry), "repair_attempt": True})
            await session.commit()  # same durability reasoning as the first model call, above

        final_text = repair_result.output_text
        parsed, error = validate_mission_output(final_text)

        if parsed is None:
            # Repair also failed: preserve the raw response (not in logs) and fail cleanly.
            await commit_artifact(
                session, deps.object_store, tenant_id=mission.tenant_id, mission_id=mission.id,
                task_id=task.id, agent_id=agent.id, agent_version_id=agent_version.id,
                artifact_type=ArtifactType.raw_model_response, title=f"{task.title} (invalid output)",
                content=(final_text or "").encode("utf-8"), mime_type="text/plain",
            )
            await _fail(deps, session, mission, task, agent, correlation_id, actor,
                        f"Output failed validation even after repair: {error}")
            return

    commit_result = await commit_artifact(
        session, deps.object_store, tenant_id=mission.tenant_id, mission_id=mission.id, task_id=task.id,
        agent_id=agent.id, agent_version_id=agent_version.id, artifact_type=ArtifactType.mission_output,
        title=parsed.title, content=final_text.encode("utf-8"), mime_type="application/json",
    )
    if commit_result.newly_created:
        await _publish(
            deps, session, EventType.artifact_created, mission, task, agent, correlation_id, actor,
            data={"artifact_id": str(commit_result.artifact.id)},
        )

    task.output_artifact_id = commit_result.artifact.id
    await session.commit()  # artifact + its ownership on the task are durable before we
    # ever claim the task "completed" — a crash right here leaves a committed artifact
    # and a task still `running`, which the next resume finds via `find_committed` and
    # reconciles onto (spec §15 "object storage failure -> artifact not marked
    # complete, task remains retryable", applied to the mirror case of the DB write
    # lagging a successful upload).

    task.status = TaskStatus.completed.value
    task.completed_at = func.now()
    await _publish(deps, session, EventType.task_completed, mission, task, agent, correlation_id, actor)

    mission.status = MissionStatus.completed.value
    mission.completed_at = func.now()
    await _publish(deps, session, EventType.mission_completed, mission, task, agent, correlation_id, actor)


async def _fail(deps, session, mission, task, agent, correlation_id, actor, reason: str) -> None:
    task.status = TaskStatus.failed.value
    task.completed_at = func.now()
    await _publish(deps, session, EventType.task_failed, mission, task, agent, correlation_id, actor,
                    data={"reason": reason})
    mission.status = MissionStatus.failed.value
    mission.completed_at = func.now()
    await _publish(deps, session, EventType.mission_failed, mission, task, agent, correlation_id, actor,
                    data={"reason": reason})


def _model_completed_data(telemetry: dict) -> dict:
    """Payload of `model.completed`. `usage_estimated` is only present when the provider
    returned text without usage figures, so the audit trail shows a priced-by-estimate call."""
    data = {"provider": telemetry["provider"], "model": telemetry["model"]}
    if telemetry.get("usage_estimated"):
        data["usage_estimated"] = True
    return data


async def _publish(deps: EngineDeps, session, event_type: EventType, mission, task, agent,
                    correlation_id, actor, *, data: dict | None = None) -> None:
    event = build_event(
        event_type=event_type, tenant_id=mission.tenant_id, correlation_id=correlation_id, actor=actor,
        service="mission-engine", mission_id=mission.id, task_id=task.id, agent_id=agent.id, data=data or {},
    )
    await deps.event_publisher.publish(event, session)
