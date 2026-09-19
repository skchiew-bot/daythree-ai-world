"""The Phase 0 `AgentRuntimeAdapter` (spec §10): a small custom durable state machine,
not LangGraph (see docs/adr/ADR-004-agent-runtime-adapter.md for why).

Durability model: `execute()` persists a checkpoint via the injected `CheckpointStore`
*before* calling the model gateway (stage `prompt_assembled`) and *after* it returns
(stage `model_responded`) — not just at the end. If the process dies between those two
writes, `resume()` reconstructs the model request from the stored checkpoint state and
picks up exactly where it left off:

- resuming from `prompt_assembled` re-issues the (not-yet-made) model call — safe,
  because no model call happened yet, so there's nothing to duplicate.
- resuming from `model_responded` does NOT call the model again — the response is
  already in the checkpoint, so replaying it is what makes retry-without-duplication
  (TC-P0-007, TC-P0-010) hold for the runtime layer specifically.
"""
from __future__ import annotations

from dataclasses import dataclass

from contracts.enums import RuntimeCheckpointStatus
from contracts.ids import new_id
from contracts.model import ModelRequest
from contracts.policy import BudgetPolicy
from contracts.runtime import Checkpoint, RunContext, RunHandle, RunResult
from model_gateway.gateway import ModelGateway

from agent_runtime.checkpoint_store import CheckpointStore
from agent_runtime.prompts.assembler import assemble_prompt
from agent_runtime.usage import UsageProvider


@dataclass
class DurableAgentRuntimeAdapter:
    model_gateway: ModelGateway
    checkpoint_store: CheckpointStore
    # Required, not defaulted: a zero-usage fallback is exactly the pre-R0 defect (the
    # budget could never trip on calls, cost or runtime). Consulted before EVERY gateway
    # call: the first execute, the output-repair execute and a resume after a crash.
    usage_provider: UsageProvider

    async def initialize_run(self, context: RunContext) -> RunHandle:
        return RunHandle(run_id=new_id(), context=context)

    async def execute(self, handle: RunHandle) -> RunResult:
        context = handle.context
        assembly = assemble_prompt(context)

        # Sequence must continue from whatever this task's highest existing checkpoint
        # is, NOT hardcode 1 — `execute()` is called a second time (a fresh RunHandle,
        # same task_id) for the one-shot repair re-prompt in
        # `mission_engine.engine.task_executor` when the first output fails output-
        # contract validation. Hardcoding `sequence=1` here made that second call
        # collide with the first attempt's own sequence=1 row on
        # `uq_checkpoints_task_sequence`, which — because `CheckpointStore.save` commits
        # — surfaced as an uncaught `IntegrityError` that left the task stuck `running`
        # forever (every resume attempt replayed the same invalid output and hit the
        # repair path again). Found by code review before this was ever exercised.
        latest = await self.checkpoint_store.latest_for_task(context.task_id)
        next_sequence = latest.sequence + 1 if latest is not None else 1

        prompt_checkpoint = await self.checkpoint_store.save(
            Checkpoint(
                run_id=handle.run_id,
                task_id=context.task_id,
                mission_id=context.mission_id,
                agent_id=context.agent_id,
                sequence=next_sequence,
                status=RuntimeCheckpointStatus.created,
                state={
                    "stage": "prompt_assembled",
                    "system_prompt": assembly.system_prompt,
                    "user_prompt": assembly.user_prompt,
                    "assembled_prompt_hash": assembly.assembled_prompt_hash,
                    "provider": context.model_provider,
                    "model": context.model_name,
                    "max_output_tokens": context.budget_policy.max_output_tokens,
                    "budget_policy": context.budget_policy.model_dump(),
                },
            )
        )

        return await self._call_model_and_checkpoint(handle.run_id, prompt_checkpoint)

    async def checkpoint(self, handle: RunHandle) -> Checkpoint:
        latest = await self.checkpoint_store.latest_for_task(handle.context.task_id)
        if latest is None:
            raise RuntimeError("No checkpoint exists yet for this run — call execute() first.")
        return latest

    async def resume(self, checkpoint: Checkpoint) -> RunResult:
        stage = checkpoint.state.get("stage")

        if stage == "model_responded":
            # The model already answered before the crash — replay it, call nothing.
            return RunResult(
                run_id=checkpoint.run_id,
                succeeded=True,
                output_text=checkpoint.state["raw_response_text"],
                final_checkpoint=checkpoint,
            )

        if stage == "prompt_assembled":
            return await self._call_model_and_checkpoint(checkpoint.run_id, checkpoint)

        raise RuntimeError(f"Unknown checkpoint stage '{stage}'; cannot resume.")

    async def cancel(self, handle: RunHandle) -> None:
        await self.checkpoint_store.save(
            Checkpoint(
                run_id=handle.run_id,
                task_id=handle.context.task_id,
                mission_id=handle.context.mission_id,
                agent_id=handle.context.agent_id,
                sequence=999,
                status=RuntimeCheckpointStatus.superseded,
                state={"stage": "cancelled"},
            )
        )

    async def _call_model_and_checkpoint(self, run_id, prompt_checkpoint: Checkpoint) -> RunResult:
        state = prompt_checkpoint.state
        request = ModelRequest(
            provider=state["provider"],
            model=state["model"],
            system_prompt=state["system_prompt"],
            user_prompt=state["user_prompt"],
            max_output_tokens=state["max_output_tokens"],
        )
        budget_policy = BudgetPolicy(**state["budget_policy"])

        usage = await self.usage_provider.usage_for_task(prompt_checkpoint.task_id)
        outcome = await self.model_gateway.generate(request, budget_policy=budget_policy, usage=usage)

        response_checkpoint = await self.checkpoint_store.save(
            Checkpoint(
                run_id=run_id,
                task_id=prompt_checkpoint.task_id,
                mission_id=prompt_checkpoint.mission_id,
                agent_id=prompt_checkpoint.agent_id,
                sequence=prompt_checkpoint.sequence + 1,
                status=RuntimeCheckpointStatus.created,
                state={
                    "stage": "model_responded",
                    "raw_response_text": outcome.response.text,
                    "provider": outcome.response.provider,
                    "model": outcome.response.model,
                    "input_tokens": outcome.response.input_tokens,
                    "output_tokens": outcome.response.output_tokens,
                    "latency_ms": outcome.response.latency_ms,
                },
            )
        )

        return RunResult(
            run_id=run_id,
            succeeded=True,
            output_text=outcome.response.text,
            model_response=outcome.response,
            model_telemetry=outcome.telemetry.model_dump(mode="json"),
            failed_attempt_telemetry=[t.model_dump(mode="json") for t in outcome.failed_attempts],
            final_checkpoint=response_checkpoint,
        )
