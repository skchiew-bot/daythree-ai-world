# ADR-012: Twin Merge (Succession)

Status: **Accepted for planning** (2026-09-18). Gate review folded in. No implementation has started.
Builds on ADR-009 (rooms, live), ADR-010 (twins, unbuilt) and ADR-011 (ledger, unbuilt). The
executable phase is `X1` in `docs/architecture/DIGITAL_TWIN_PROGRAM_BUILD_PLAN.md`.

## Context

Operator intent (Chiew Sin Kwang, 2026-09-18): once two or more twins "understood their roles" and
reach operational excellence together, they should merge into one new twin; the old twins are then
"considered as Merged where they no longer exist in the digital world." The operator rejected true
deletion once the append-only audit trail was raised, and accepted that the merge must be
human-approved, not self-initiated, because the guardian charter binds every agent to propose only.

Why a separate ADR: ADR-011 fixes the roster question (O1) and the ledger; this mechanic changes
agent *identity* over time, touches ledger conservation, and reuses the room lifecycle, so it needs
its own gate and its own rollback.

Facts in current code that shape the design:

- `Agent.lifecycle_state` is a `String(32)` holding `draft` / `active` / `suspended`
  (`packages/contracts/enums.py` lines 30 to 33). No native Postgres enum, so a new value is a
  code change only. No column on `agents` references another agent.
- `agent_versions` are immutable and `active_version_id` flips between them: identity succession at
  the version level already exists. This ADR lifts the same idea one level up.
- ADR-009's `release_assignment()` frees a room by stamping `released_at`; it deletes nothing.
- ADR-011 part 2: balances are derived from `twin_ledger_entries`, never stored; one locked anchor
  row per `(tenant_id, agent_id)`; "no transfers between agents, tenants or humans."

## Decision

A merge creates a **successor** twin and retires its **predecessors**. Nothing is deleted, no credit
is minted, destroyed or transferred, and the predecessors can never act again.

1. **`merged` is a terminal lifecycle state.** New enum value `AgentLifecycleState.merged`.
   `activate_agent` and `suspend_agent` return 409 for a merged agent; mission creation and
   `_load_external_task` refuse a merged `assigned_agent_id`; the admin registry renders no action
   button for it. A merged agent keeps its rows, its `agent_code`, its versions, its tasks, its
   artifacts and its audit events, all queryable by `agent_id`.
2. **Two normalized tables, migration `0007_agent_merges`.**
   - `agent_merges`: `id`, `tenant_id`, `successor_agent_id` (FK `agents.id`), `decided_by` (user
     id), `rationale` (`String(500)`), `idempotency_key` (unique), `approved_at`, `created_at`.
   - `agent_merge_predecessors`: `merge_id` (FK), `tenant_id`, `predecessor_agent_id`, with
     `UNIQUE(tenant_id, predecessor_agent_id)` so an agent is a predecessor exactly once, ever, and a
     composite FK to `agents(tenant_id, id)` so cross-tenant lineage is impossible at the database.
     The migration adds the matching `UNIQUE(tenant_id, id)` index on `agents`; no existing table
     gains a column.
   - Inserts run inside `begin_nested()`; `IntegrityError` becomes 409 (the pattern at
     `artifact_service/service.py` lines 83 to 92, adopted by ADR-011 C3).
3. **The council proposes, the operator executes.** The standing council (ADR-011 part 3) may attach
   a merge proposal to its dated report. Only an `operator` / `tenant_admin` / `platform_admin`
   actor may execute, through `POST /api/v1/agents/merge`, behind a router-local role constant that
   excludes `agent_runtime` with a 403 test. The request body carries explicit
   `predecessor_agent_ids` and the successor's full creation payload (new `agent_code`, display
   name, first version). A council proposal reference, if supplied, is stored as an opaque string
   and never dereferenced into identities. No hook, `external_manual` path or task-completion
   payload can reach this route. The operator may also merge without any council proposal.
4. **Preconditions on execute.** Every predecessor is `active` or `suspended` in the caller's tenant
   and has no task in `queued`, `running` or `waiting` (409 otherwise; the operator drains or
   cancels first). The successor's `agent_code` is new (400 on collision, never a 500 from
   `uq_agents_tenant_code`).
5. **One transaction, in this order.** Lock the ledger anchor rows of every predecessor and the
   successor in ascending `agent_id` order; insert `agent_merges` and its predecessor rows; create
   the successor through the existing `create_agent` path (which calls `ensure_assignment`, ADR-009);
   flip each predecessor to `merged`; call the existing `release_assignment()` for each; emit
   `agent.merged` (new `EventType`) once per predecessor and once for the successor, payload limited
   to `merge_id`, ids and counts.
6. **Lineage-aware balance, made safe.** A twin's balance is the sum of `twin_ledger_entries` over
   its full lineage, resolved by a recursive CTE over `agent_merge_predecessors` with `DISTINCT`, a
   hard depth cap and a visited set. Every ledger read, mint and debit first resolves
   `lineage_head(agent_id)` and locks that single anchor, so a lineage has exactly one lock point.
   Since `merged` is terminal, no new entry can ever be written against a predecessor, and the head
   anchor is the only live one. Conservation holds by construction: `balance(successor)` equals the
   sum of every entry ever written across the lineage.
7. **The world view uses an allow-list.** `agent_rooms.py` filters `lifecycle_state IN (draft,
   active)` instead of `!= suspended`, so `merged` and any future state are invisible by default and
   never lazily re-assigned a room.
8. **Ordering.** `0007` ships after ADR-011's `0005_twin_economy`, so the lineage read is defined
   from the first merge. Merging without a ledger is not offered.

## Gate Review Outcome (guardian-gatekeeper, 2026-09-18)

Verdict on the first draft (JSONB predecessor array, one-level balance union, `merged` not
enforced anywhere): **BLOCK + ALTERNATIVE** on the balance read and on non-terminal `merged`;
**PASS WITH CONDITIONS** on the merge table, the proposes/executes split and the room reuse. The
decision above *is* the alternative. Findings, each verified against current code by the chair:

- **F1 HIGH, retired twin reappears.** `services/api/routes/agent_rooms.py` line 79 filters
  `lifecycle_state != suspended`; a `merged` agent passes and the backfill loop at lines 88 to 93
  calls `ensure_assignment`, so the released room is re-allocated on the next 3-second poll.
  *Adopted:* allow-list (decision 7) plus a regression test that a merged agent is absent from the
  response and holds no active assignment after a `GET`.
- **F2 CRITICAL, un-merge in one click.** `apps/admin-web/src/pages/AgentRegistry.tsx` line 43
  renders Activate for any non-active agent that has an `active_version_id`; `activate_agent`
  (`services/api/routes/agents.py` lines 172 to 198) has no lifecycle guard, so a predecessor
  returns to `active` and re-enters the room path while still in the successor's lineage: one pool
  of credits, two spenders, no mint recorded. *Adopted:* terminal state with 409s and a hidden
  button (decision 1), tested at both layers.
- **F3 HIGH, JSONB array double-counts.** A JSONB `predecessor_agent_ids` has no FK, no uniqueness
  and no tenant predicate; a retried or concurrent execute lists an agent twice and the balance
  `SUM` doubles with no ledger entry and no audit row. *Adopted:* normalized predecessor table with
  `UNIQUE(tenant_id, predecessor_agent_id)`, composite FK, `begin_nested()`, idempotency key
  (decision 2).
- **F4 HIGH, anchor lock spans one agent, balance spans many.** ADR-011 C4's lock is per
  `(tenant_id, agent_id)`; a purchase against the successor and a debit against a still-live
  predecessor lock different anchors and both pass the debt floor. *Adopted:* `lineage_head`
  resolution before every lock, merge transaction locks all anchors in order, predecessors can
  never be written to (decisions 1, 5, 6), plus a concurrent predecessor-versus-successor purchase
  test asserting exactly one succeeds.
- **F5 HIGH, chained merges lose credits.** A one-level union for A+B→C then C+D→E drops A and B
  from every balance. *Adopted:* recursive `DISTINCT` depth-capped CTE (decision 6) and a test that
  `balance(E)` equals the sum over A, B, C, D, E to the cent.
- **F6 HIGH, a "retired" twin still works.** `create_mission_route` (`services/api/routes/missions.py`)
  passes `assigned_agent_id` through with no agent lookup; `_load_external_task`
  (`services/api/routes/tasks.py`) checks only `runtime_adapter`; nothing gates on
  `lifecycle_state`. A merged predecessor could take a mission, close it and have the artifact
  accepted. In-flight tasks keep FK integrity (`tasks.assigned_agent_id` is a plain FK) but lose
  their room and vanish from the world view. *Adopted:* `merged` guards on mission creation and
  task load, and the no-open-tasks precondition (decisions 1, 4).
- **F7 MEDIUM, proposal dereference is the back door.** If the execute body accepted a proposal id
  the server resolved into identities, text a twin wrote into its own artifact could become the
  merge the operator's click authorizes: the original "they reregistered themselves", reintroduced.
  *Adopted:* explicit identities only, opaque proposal reference, 422 for a body that names only a
  reference (decision 3).
- **F8 MEDIUM, `rationale` reopens D1/D2.** Unbounded free text about why two twins underperformed
  will name real clients or people, then be read by the council and rendered in the world.
  *Adopted:* `String(500)`, never copied into `audit_events.payload`, excluded from council- and
  twin-visible reads until ADR-011's D2 redaction gate exists, D3's forbidden-content list applies.
- **F9 LOW, unaudited transition.** `EventType` (`packages/contracts/enums.py` lines 110 to 113)
  has `agent.created` / `version_created` / `activated` / `suspended` and no merge event.
  *Adopted:* `agent.merged` (decision 5).
- **F10 LOW, code reuse is a 500.** `uq_agents_tenant_code` is unconditional and predecessors keep
  their rows, so a predecessor's code is burned forever; `create_agent` has no `IntegrityError`
  handling. *Adopted:* successor takes a new code, 400 on collision (decision 4); `0007` after
  `0005` (decision 8).

Conditions M1 to M10 map one-to-one onto the fixes above and are restated as exit criteria for
phase X1 in the build plan.

## Consequences

- One additive migration (`0007`): two new tables, one new unique index on `agents`, no new
  columns on existing tables. Rollback drops the two tables and the index; merged agents stay
  `merged` (the enum value lives in code) and can be re-activated by hand if the mechanic is
  withdrawn, which is the honest cost of rollback and is recorded here.
- The operator gains one control: approve a merge, name the successor. The council gains one
  proposal type. Twins gain nothing they can trigger.
- Every screen that shows a successor's balance or track record must say it includes the lineage,
  and the world view shows only the successor's room.
- Predecessor history is never re-attributed: a task closed by A stays A's task. Reports that roll
  up "the successor's work" do so by lineage query, and say so.

## Open decisions for the operator

- **O6.** Whether execute requires council evidence at all, or the operator's word alone suffices
  (the design allows both).
- **O7.** Minimum evidence before a council may propose (default proposal: each predecessor has at
  least 10 accepted artifacts and the pair has shared at least 5 missions in the trailing 60 days).
- **O8.** Depth cap for the lineage CTE (default 16).
- **O9.** Whether the successor's display name and description are operator-typed at execute time
  (default) or drafted by the council for the operator to edit.

## Rollback Path

Revert the X1 PRs and run `0007`'s `downgrade()`. ADR-009, ADR-010 and ADR-011 keep working because
nothing in `0007` alters their tables beyond the added unique index, which the downgrade removes.
Agents left in `merged` are listed by the downgrade's log output so the operator can activate them
by hand if the successor is to be abandoned.
