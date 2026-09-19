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
