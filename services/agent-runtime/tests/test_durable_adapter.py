import json

import pytest

from agent_runtime.adapters.durable_adapter import DurableAgentRuntimeAdapter
from agent_runtime.checkpoint_store import InMemoryCheckpointStore
from contracts.enums import RuntimeCheckpointStatus
from contracts.ids import new_id
from contracts.policy import BudgetPolicy, ToolPolicy
from contracts.runtime import RunContext
from model_gateway.gateway import ModelGateway
from model_gateway.providers.mock import MockModelProvider

pytestmark = pytest.mark.unit


def make_context(**overrides) -> RunContext:
    defaults = dict(
        tenant_id=new_id(), mission_id=new_id(), task_id=new_id(), agent_id=new_id(),
        agent_version_id=new_id(), correlation_id=new_id(),
        system_prompt="You are Atlas.", mission_objective="Research X.",
        task_instructions="Produce a structured note.",
        tool_policy=ToolPolicy(allow=["artifact.write"], deny=["*"]),
        budget_policy=BudgetPolicy(),
        model_provider="mock", model_name="claude-sonnet-5",
    )
    defaults.update(overrides)
    return RunContext(**defaults)


def make_adapter() -> tuple[DurableAgentRuntimeAdapter, InMemoryCheckpointStore]:
    store = InMemoryCheckpointStore()
    gateway = ModelGateway(providers={"mock": MockModelProvider()})
    return DurableAgentRuntimeAdapter(model_gateway=gateway, checkpoint_store=store), store


@pytest.mark.asyncio
async def test_execute_produces_two_checkpoints_and_a_valid_result():
    adapter, store = make_adapter()
    context = make_context()
    handle = await adapter.initialize_run(context)

    result = await adapter.execute(handle)

    assert result.succeeded is True
    assert result.output_text is not None
    json.loads(result.output_text)  # must be valid JSON (mock provider output contract)
    assert result.model_telemetry is not None

    history = store._by_task[context.task_id]
    assert [c.state["stage"] for c in history] == ["prompt_assembled", "model_responded"]
    assert history[0].status == RuntimeCheckpointStatus.created
    assert history[1].sequence == history[0].sequence + 1


@pytest.mark.asyncio
async def test_resume_from_prompt_assembled_completes_the_run_tc_p0_007():
    """Simulates a worker crash right after checkpoint 1, before the model was ever
    called — resume must complete the run using the persisted prompt."""
    adapter, store = make_adapter()
    context = make_context()
    handle = await adapter.initialize_run(context)

    # Manually drive only the first half of execute(), as if the process died here.
    from agent_runtime.prompts.assembler import assemble_prompt
    from contracts.runtime import Checkpoint

    assembly = assemble_prompt(context)
    checkpoint = await store.save(
        Checkpoint(
            run_id=handle.run_id, task_id=context.task_id, mission_id=context.mission_id,
            agent_id=context.agent_id, sequence=1, status=RuntimeCheckpointStatus.created,
            state={
                "stage": "prompt_assembled", "system_prompt": assembly.system_prompt,
                "user_prompt": assembly.user_prompt, "provider": "mock", "model": "claude-sonnet-5",
                "max_output_tokens": context.budget_policy.max_output_tokens,
                "budget_policy": context.budget_policy.model_dump(),
            },
        )
    )

    result = await adapter.resume(checkpoint)

    assert result.succeeded is True
    assert result.final_checkpoint.state["stage"] == "model_responded"
    assert len(store._by_task[context.task_id]) == 2  # the resumed one plus the new one


@pytest.mark.asyncio
async def test_resume_from_model_responded_does_not_call_the_model_again_tc_p0_010():
    """Simulates a crash AFTER the model responded but before the task was marked
    complete — resume must replay the stored response, not invoke the model again
    (this is what prevents a duplicate committed artifact on retry)."""
    adapter, store = make_adapter()
    context = make_context()
    handle = await adapter.initialize_run(context)

    first_result = await adapter.execute(handle)
    checkpoint_after_response = first_result.final_checkpoint
    calls_after_first_execute = len(store._by_task[context.task_id])

    resumed_result = await adapter.resume(checkpoint_after_response)

    assert resumed_result.output_text == first_result.output_text
    assert resumed_result.model_telemetry is None  # no new model call → no new telemetry
    # resuming from the terminal stage must not add another checkpoint
    assert len(store._by_task[context.task_id]) == calls_after_first_execute


@pytest.mark.asyncio
async def test_execute_called_twice_for_the_same_task_does_not_collide_on_sequence():
    """Regression test: `task_executor` calls `execute()` a second time on the same
    `task_id` (a fresh `RunHandle`, same task) for the one-shot output-validation
    repair re-prompt. Before this was fixed, `execute()` hardcoded `sequence=1` for its
    first checkpoint every time, so the repair round's checkpoint collided with the
    original attempt's `(task_id, sequence=1)` row on `uq_checkpoints_task_sequence`
    and — since checkpoint saves commit — surfaced as an uncaught `IntegrityError` that
    left the task stuck `running` forever on every resume. Sequence numbers for one
    task must keep increasing across separate `execute()` calls, not just within one.
    """
    adapter, store = make_adapter()
    context = make_context()

    first_handle = await adapter.initialize_run(context)
    first_result = await adapter.execute(first_handle)

    repair_handle = await adapter.initialize_run(context)  # fresh handle, same task_id
    repair_result = await adapter.execute(repair_handle)

    history = store._by_task[context.task_id]
    sequences = [c.sequence for c in history]
    assert sequences == sorted(set(sequences)), "checkpoint sequences must be unique and increasing"
    assert len(sequences) == 4  # two checkpoints per execute() call, no collision
    assert repair_result.succeeded is True
    assert first_result.final_checkpoint.sequence < repair_result.final_checkpoint.sequence
