# Council and Guardian Ledger

Append-only. This is the project audit log the guardian charter (rule 4) requires for decisions
made by agents, which live outside the platform's own `audit_events` table. Never edit or delete an
entry; correct by appending. One entry per line block, newest at the bottom. UTC timestamps.

Entry shape: `timestamp | actor | kind | subject | verdict/decision | evidence`.

---

2026-09-18T14:20:46Z | guardian-gatekeeper (via chair Fable 5.1) | gate review | ADR-011 Digital Twin Program (design brief) | BLOCK + ALTERNATIVE on minting/upkeep mechanics; PASS WITH CONDITIONS C1..C10 on twins, council, operator model, autonomy | Findings F1..F10 with file:function paths recorded in `docs/adr/ADR-011-digital-twin-program.md`, section "Gate Review Outcome"

2026-09-18T14:20:46Z | guardian-data-warden (via chair Fable 5.1) | data-exposure review | ADR-011 operator-learning, council inputs/outputs, hook payloads | PASS WITH CONDITIONS D1..D5 | Confirmed `audit_events.payload` carries raw `str(exc)` (task_executor.py 114..127); conditions recorded in ADR-011, section "Data-warden review"

2026-09-18T14:20:46Z | council (Architect in-context, Skeptic, Pragmatist, Critic; `council` skill protocol) | decision | Build the digital twin program, and in what shape | Consensus: twins first, roster capped at 5, ledger designed now but started only at Gate E, minting never hook-driven, ratings never the sole promotion input; strongest dissent (Skeptic, Critic): do not build the ledger yet | Raw positions and verdict recorded in ADR-011, section "Council (2026-09-18)"

2026-09-18T14:20:46Z | chair (Fable 5.1) | decision | ADR-011 accepted for planning; build plan written | Accepted with all gate and warden conditions folded in as exit criteria; no implementation started; operator decisions O1..O5 open | `docs/adr/ADR-011-digital-twin-program.md`, `docs/architecture/DIGITAL_TWIN_PROGRAM_BUILD_PLAN.md`

2026-09-18T23:37:51Z | guardian-gatekeeper (via chair Fable 5.1) | gate review | ADR-012 twin merge mechanic (draft design, pre-ADR) | BLOCK + ALTERNATIVE on the lineage-aware balance read and on non-terminal `merged`; PASS WITH CONDITIONS on the merge table, council-proposes/operator-executes split, and reuse of ADR-009 room release | Findings F1..F10 with file:line paths recorded in `docs/adr/ADR-012-twin-merge.md`, section "Gate Review Outcome"; F1, F2, F9 re-verified in code by the chair before recording. Rejected as drafted: JSONB predecessor array; one-level lineage union; `merged` as a non-terminal state.

2026-09-18T23:37:51Z | chair (Fable 5.1) | decision | ADR-012 accepted for planning with the gatekeeper's alternative as the decision | Merged agents are terminal; normalized predecessor table with UNIQUE(tenant_id, predecessor_agent_id); recursive depth-capped lineage balance; lineage_head anchor lock; allow-list world read; explicit identities in the execute body; no implementation started; operator decisions O6..O9 open | `docs/adr/ADR-012-twin-merge.md`

2026-09-18T23:52:11Z | guardian-gatekeeper (via chair Fable 5.1) | gate review | ADR-013 twin R&D allowance and AI-token metering (design brief) | BLOCK + ALTERNATIVE on execution, metering, knowledge scoping and kill switch; "credits unlock, never convert" PASSES the no-fiat rule conditional on a stepped, ceiling-bound f | Findings F1..F10 in `docs/adr/ADR-013-rd-allowance-and-metering.md`; F1 (durable_adapter.py:128 zero BudgetUsage), F2 (gateway.py:59 vs 72-103), F3 (telemetry.py:21 default price), F6 (tools.py:62-70, ToolRegistry unused outside tests) re-verified in code by the chair. Pre-existing Phase 0 defect: per-task budget enforces only max_output_tokens; no real provider key configured, so no money spent to date.

2026-09-18T23:52:11Z | guardian-data-warden (via chair Fable 5.1) | data-exposure review | ADR-013 R&D prompts, knowledge_note artifacts, knowledge_read scoping, 3D idle movement | PASS WITH CONDITIONS D6..D11 | assembler.py:52-56 dumps available_context unfiltered; knowledge_read has no ACL; sql_checkpoint_store.py:30-42 persists full prompts; conditions recorded in ADR-013

2026-09-18T23:52:11Z | council (Architect in-context, Skeptic, Pragmatist, Critic; `council` skill protocol) | decision | Should twins spend credits to unlock operator-funded R&D tokens, and how is real-world task cost metered | Consensus: one enforcement path (existing BudgetPolicy made real), R&D only in the worker, external twins get zero self-directed spend, tiny initial ceilings, declared numbers never feed minting or allowances; strongest dissent (Skeptic): fund no R&D until learning persists, accepted in part (notes ship with first R&D mission) | Raw positions in ADR-013, section "Council (2026-09-18)"

2026-09-18T23:52:11Z | chair (Fable 5.1) | decision | ADR-013 accepted for planning; phases R0..R4 and W1 added to the build plan | Architect's A2 auto-start dropped; R0 budget fix is a prerequisite and a Phase 0 defect; ADR-011 part 4 amended (profile reaches twins by input_context injection, not the knowledge_read tool); operator decisions O10..O14 open | `docs/adr/ADR-013-rd-allowance-and-metering.md`, `docs/architecture/DIGITAL_TWIN_PROGRAM_BUILD_PLAN.md`
