# ADR-004: Agent Runtime Adapter

## Context

Spec §10 defines the `AgentRuntimeAdapter` protocol (`initialize_run` / `execute` /
`checkpoint` / `resume` / `cancel`) and explicitly says "the first adapter may use
LangGraph or a custom durable runtime" — leaving the choice open, with the one hard rule
that no business logic may call the chosen runtime directly outside the adapter layer.
Phase 0's actual workload per task is one prompt assembly + one model call + one output
validation (with at most one repair re-prompt) — not a multi-step agentic graph.

## Options Considered

1. **LangGraph** as the runtime, with Phase 0's single-step flow modeled as a trivial
   2-node graph.
2. **A custom durable adapter** (`services/agent-runtime/agent_runtime/adapters/
   durable_adapter.py`): a small state machine that persists a checkpoint before and
   after the model call via an injected `CheckpointStore` port.

## Decision

Custom durable adapter, not LangGraph.

## Rationale

- LangGraph is designed for multi-node agentic graphs with branching, tool loops, and
  cyclic execution — genuinely valuable once Phase 1+ needs multi-step or multi-agent
  workflows, but it would be pure overhead for Phase 0's single linear step, adding a
  dependency whose checkpoint/persistence model would need to be adapted to spec §8.8's
  `runtime_checkpoints` table shape anyway.
- The custom adapter's checkpoint strategy is exactly two points — after prompt assembly
  (`stage: "prompt_assembled"`) and after the model responds (`stage:
  "model_responded"`) — chosen specifically because those are the two places a worker
  crash actually needs to be distinguished for TC-P0-007/TC-P0-010: crashing before any
  model call happened (safe to redo) versus crashing after the model already answered
  (must NOT be redone, or a second, different model output could get committed as if it
  were a duplicate of the first).
- Both options satisfy the protocol identically from the Mission Engine's point of view
  — `mission_engine` only ever imports `AgentRuntimeAdapter`/`RunContext`/`RunHandle`/
  `Checkpoint`/`RunResult` from `packages/contracts` and `services/agent-runtime`'s
  protocol module, never `DurableAgentRuntimeAdapter` by name outside of the one place
  that constructs it (`services/worker/deps.py`).

## Consequences

- **A checkpoint save commits the database session, not just flushes it**
  (`mission_engine/checkpoints/sql_checkpoint_store.py::SqlCheckpointStore.save`) —
  this was *not* the original design and was corrected during self-review before this
  build's first execution: `task_executor.execute_task` runs on one session the worker
  only commits once, at the very end, so a checkpoint that merely flushed would still
  be sitting in an open transaction and would be rolled back by the very crash it was
  meant to survive. `task_executor.py` also commits explicitly right after recording
  each model invocation and right after committing an artifact, for the same reason —
  see the inline comments at each call site for exactly which crash window each commit
  closes.
- No support (yet) for multi-step agent plans, tool-calling loops, or branching —
  exactly matching Phase 0's explicit scope (spec §3: "no multi-agent collaboration,"
  "no dynamic skill progression").
- The checkpoint `state` dict is untyped JSON (by design — it must serialize to
  `runtime_checkpoints.state` JSONB) with two known stage shapes
  (`prompt_assembled`, `model_responded`); a third stage would need to be added
  carefully alongside `resume()`'s dispatch logic.

## Rollback Path

Implement a `LangGraphAgentRuntimeAdapter` satisfying the same `AgentRuntimeAdapter`
protocol and swap the one construction site in `services/worker/deps.py`
(`build_engine_deps`) — no change needed to `mission_engine`, the API, or the checkpoint
table schema, since `Checkpoint.state` is already an open JSON document.
