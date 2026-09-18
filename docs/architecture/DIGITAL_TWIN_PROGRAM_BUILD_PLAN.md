# Digital Twin Program: Build Plan

Decision record: `docs/adr/ADR-011-digital-twin-program.md` (read it first; it carries the council
verdict, the gate conditions C1 to C10 and the data-warden conditions D1 to D5 that this plan turns
into exit criteria). Status: **planned, not started.** Every phase below is written so a Sonnet 5
session can execute it end to end with the paste-ready handoff prompt at the end of the phase.

## How this program runs

**Roles and model routing.**

| Role | Model | Does |
|---|---|---|
| Chair | Fable 5.1 | Plans a phase, convenes the council, reviews the PR before the operator sees it, synthesizes the weekly report |
| Builder | Sonnet 5 | Executes one phase handoff at a time on a branch, TDD, opens the PR |
| Guardians | as defined in `~/.claude/agents/guardian-*.md` | Gatekeeper before each phase; data-warden before anything is pushed that contains review text; SRE and incident-commander when something breaks |
| Operator | Chiew Sin Kwang | The only source of acceptance, ratings, profile content, "merge it" and autonomy promotion |

**Non-negotiables inherited from the charter and the repo.**

- Every change: branch, PR, all four CI jobs green, then the operator's explicit "merge it".
- Nothing weakens auth, tenant isolation, rate limits, validation or the audit trail.
- No secrets in chat or tracked files; machine-specific config lives in gitignored files with a
  tracked `.example`.
- Migrations are additive only (`create_all(checkfirst=True)` plus an explicit per-index sweep, the
  ADR-009 pattern), each tested from a fresh DB and from the prior revision.
- Wherever a number comes from a self-report (external agent cost, external agent tool use), the UI
  and reports label it "declared, not measured".
- Every council decision and every gate verdict is appended to `docs/council/LEDGER.md`.

**Definition of "done" for a phase:** exit criteria met, tests listed in the phase green locally
and in CI, the completion report's "Beyond Phase 0" section updated, the ledger appended, the
operator has merged.

## Phase map

| Phase | Name | Depends on | Starts when |
|---|---|---|---|
| T1 | Twins: identity and registration (ADR-010 A) | nothing | now |
| T2 | Twins: lifecycle closure, reaper, per-task artifact (ADR-010 B, corrected) | T1 | T1 merged |
| T3 | Twins: hook wiring for a 5-persona roster (ADR-010 C) | T2 | T2 merged |
| T4 | Twins in the 3D world (ADR-010 D) | T3 | T3 merged |
| Gate E | Evidence gate | T3 running for two weeks | thresholds in O2 met |
| L1 | Contribution ledger: accept/reject, mint, upkeep | Gate E | operator opens Gate E |
| L2 | Materials and workshop (spend, 3D render) | L1 | L1 merged |
| X1 | Twin merge / succession (ADR-012) | L1 | L1 merged, operator answers O6..O9 |
| C1 | Council: reports and proposals | L1 | L1 merged |
| M1 | Operator model: reviews, profile docs, knowledge_read | L1 | L1 merged |
| A1 | Autonomy graduation proposals | C1 + M1 | both merged |

T1 to T4 are the ADR-010 phases with the corrections from ADR-011's gate review applied; where this
document and ADR-010 disagree, this document wins (it is newer and was gated against the code as it
is now).

---

## T1. Twins: identity and registration

**Goal.** A scoped credential can register a session and a subagent spawn as governed objects, and
every persona in the roster exists as a governed `agents` row with the right autonomy and tool
policy, without the hook ever being able to elevate itself.

**Deliverables.**

- Migration `0004_agent_runtime_sessions` (`down_revision = "0003_agent_room_assignments"`):
  `agent_runtime_sessions` (tenant-scoped, FK `agents.id`, nullable FK `tasks.id`,
  `external_session_ref`, `external_instance_ref`, `kind` session|subagent, `started_at`,
  `last_heartbeat_at`, `ended_at`, `outcome`), `agent_runtime_persona_slots(tenant_id, slot)`
  with a unique index (the atomic cap, ADR-010 B4), `agent_runtime_api_keys(user_id, key_hash,
  revoked_at)`.
- A service `User` row per tenant with role `agent_runtime` and an unusable password hash; a
  dependency that resolves a bearer API key (sha256 compared) to that user so `require_role` and
  tenant scoping work unchanged. The secret is printed once by a seed/issue script and never
  logged.
- `POST /api/v1/agent-runtime/sessions` (kind=session: idempotent on `external_session_ref`,
  creates a Mission with `mission_code = session uuid`, `source="agent_runtime"`; kind=subagent:
  resolves the persona from a server-side registry, creates the `agents` row and `AgentVersion`
  on first sight with `runtime_adapter="external_manual"` and a tenant-scoped `model_policy_id`,
  takes a persona slot, creates the Task `queued`, emits `task.created`/`task.assigned`, calls
  ADR-009 `ensure_assignment` inside the existing exception-contained wrapper).
- `PATCH /api/v1/agent-runtime/sessions/{id}` for heartbeat and `ended`.
- Persona registry: `services/api/persona_registry.py` mapping agent type name to display name,
  autonomy level and tool policy; unknown names bucket to `AGT-CC-GENERAL`; the initial roster
  (O1) is an allow-list, everything else is opt-in.
- Mission Control hides Start/Cancel for `source="agent_runtime"` missions (ADR-010 C4).
- **Gate condition C7 (partial):** narrow `agent_runtime`'s read scope. Introduce a
  `require_not_role(UserRole.agent_runtime)` guard (or an explicit reader-role set) on
  `artifacts.download_artifact` and `tasks.get_task`; the runtime credential may read only its own
  session and task rows.

**Tests.** Cross-tenant isolation for every new route; idempotent replay of session and subagent
registration; persona cap enforced under 10 concurrent first-sights (real Postgres); registration
survives an `ensure_assignment` exception; `agent_runtime` gets 403 on accept-shaped and download
routes; migration upgrade from `0003` and from empty.

**Exit.** A scoped-key call creates a persona row, a Mission and a Task visible in `audit_events`,
and the runtime credential cannot download artifacts.

**Handoff prompt (paste to a Sonnet 5 session in this repo):**

> Implement Phase T1 of `docs/architecture/DIGITAL_TWIN_PROGRAM_BUILD_PLAN.md` exactly as written,
> on a branch `feat/twins-t1-identity`. Read ADR-010 and ADR-011 first; where they disagree, the
> build plan wins. Follow the repo's existing patterns: `get_db_session` commit-on-return (no
> in-route commits), `get_tenant_scoped_or_404`, partial unique indexes as the concurrency
> guarantee, `create_all(checkfirst=True)` plus an index sweep in the migration, tests against
> testcontainers Postgres marked `integration`/`security`, and `pytest.mark.unit` on pure tests.
> Never paste a secret into the chat or a tracked file. Open the PR with a test plan; do not merge.

---

## T2. Twins: lifecycle closure, reaper, per-task artifact

**Goal.** Every Task opened in T1 reaches a terminal state, with a reviewable artifact when the
subagent has one to give, even if the terminal is killed.

**Deliverables.**

- `POST /api/v1/agent-runtime/sessions/{id}/close` with body `{outcome: completed|failed,
  output_text?: string, tool_call_count?: int, reason?: string}`. Drives the Task
  `queued -> running -> completed|failed` (the state machine forbids `running -> running`), emits
  `task.started` and `task.completed`/`task.failed` through `EventPublisher`, and **never touches
  the Mission** (ADR-010 B2). When `output_text` is present it is validated with
  `validate_mission_output` and committed via `artifact_service.commit_artifact` as a
  `mission_output` artifact bound to that task (ADR-011 gate F1). `tasks.py` is not modified.
- `SessionEnd` closes the Mission and fails still-open subagent tasks as `abandoned`.
- A reaper (worker-side, restartable, no resident state) fails tasks whose session heartbeat is
  older than the O2 window and records `abandoned` with the reason; the count of reaped tasks is
  the hook-loss measure Gate E reads.

**Tests.** Full close with artifact produces the expected event sequence and one `artifacts` row;
close without artifact leaves no artifact and still closes; a second close is a no-op (idempotent);
parallel subagents under one Mission close independently and the Mission stays `running`; reaper
closes a stale task and never a live one.

**Exit.** Two parallel subagents in one session produce one Mission, two closed Tasks, one artifact
each, and the reaper closes a deliberately abandoned third.

**Handoff prompt:** as T1, phase T2, branch `feat/twins-t2-lifecycle`.

---

## T3. Twins: hook wiring for the roster

**Goal.** A real Claude Code session with the roster's personas registers, closes and reaps itself
without any manual call.

**Deliverables.**

- `scripts/report_twin_lifecycle.sh` (tracked, secret-free): reads the runtime API key from a
  gitignored wrapper (`.claude/twin_env.sh`, `.example` tracked), maps `SessionStart`,
  `SubagentStart`, `SubagentStop`, `SessionEnd` payloads to the T1/T2 routes, sends only agent
  type, session id, parent session id, outcome and tool-call count (ADR-010 C6, D-warden), exits 0
  always, logs failures to `.hook-debug/`.
- `.claude/settings.local.json.example` extended with the four hooks, using the Windows-safe shape
  from PR #13 (fully-qualified `bash.exe --login`, no backgrounding).
- Validate the real hook payload field names against the installed Claude Code version before
  committing the mapping; record the version in the script header.
- The existing `report_claude_status.sh` stays as the presence fallback.

**Tests.** A shell-level test that feeds recorded hook payloads through the script against the
local stack; a fresh-session manual verification recorded in the ledger (the same standard PR #13
used: a timestamp the operator never manually produced).

**Exit.** One real session, two spawned subagents, one Mission and two closed Tasks with correct
persona rows, no plaintext secret in any new file.

**Handoff prompt:** as T1, phase T3, branch `feat/twins-t3-hooks`; the final verification needs the
operator to start a fresh session, so end the PR description with that request.

---

## T4. Twins in the 3D world

**Goal.** Spawning a subagent makes its persona walk to its room desk within one poll and return to
idle on close; a room with several concurrent Tasks shows an occupancy count; the top-level session
room shows the Mission code.

**Deliverables.** Extend `AgentRoomOut` with `occupancy` and `mission_code`; render the count on the
room panel; deprecate the presence-only hook once T3 is verified. Frontend changes only touch
`apps/admin-web/src/world/*` and `World.tsx`.

**Tests.** `npm run typecheck`, `npm run build`, the Playwright journey extended to assert the
occupancy table; a manual screenshot recorded in the ledger.

**Handoff prompt:** as T1, phase T4, branch `feat/twins-t4-world`.

---

## Gate E. Evidence gate

The council's first run (or the chair by hand) produces `docs/council/gate-e-report.md` from
structured data only (D2): closed twin tasks, artifacts produced, reaped tasks (hook-loss rate),
operator reviews recorded so far (from a temporary manual accept/reject form if M1 is not built,
otherwise from `artifact_reviews`). The operator opens the gate by appending a signed line to
`docs/council/LEDGER.md`. Default thresholds (O2): 30 closed twin tasks, 20 operator reviews,
hook-loss rate under 5% over two weeks. Nothing in L1 onward starts before this line exists.

---

## L1. Contribution ledger: accept, reject, mint, upkeep

**Goal.** The operator's acceptance of real work is the one and only way a twin earns; the twin's
upkeep is charged honestly; every balance is derivable from an append-only ledger.

**Deliverables.**

- Migration `0005_twin_economy` (`down_revision = "0004_agent_runtime_sessions"`):
  `twin_ledger_entries` (tenant_id, agent_id, kind mint|upkeep|purchase|adjustment, amount
  integer credits, source_kind, source_ref, created_by, created_at; **unique index
  `(tenant_id, kind, source_kind, source_ref)`**, C3), `twin_balance_anchors(tenant_id, agent_id)`
  one row per persona, used only as the lock target for the debt floor (C4).
- `POST /api/v1/artifacts/{id}/accept` and `/reject`, router-local role constant
  (`operator`/`tenant_admin`/`platform_admin`), 403 for `agent_runtime` (C7). Accept mints
  `source_kind="artifact", source_ref=artifact id` inside `begin_nested()`, resolving
  `IntegrityError` by re-select (C3). Emits `artifact.accepted` / `artifact.rejected` events
  (payload: ids and rating only, never free text, C10/D1).
- Upkeep: on task close, one `upkeep` entry. `external_manual`: flat fee from a tenant setting,
  `source_ref = task id`, labeled declared. `custom_durable`: multiplier times the task's summed
  `model_invocations.estimated_cost`, labeled measured (C2).
- `GET /api/v1/twins` (persona, room, derived balance, accepted/rejected counts, upkeep to date,
  label) and `GET /api/v1/twins/{agent_id}/ledger` (paginated, hard max page size).
- Admin web: Accept/Reject with rating on the Mission Detail artifact tab; a Twins page.
- Debt floor from a tenant setting; purchases (L2) check it under the anchor lock; task execution
  never checks it.

**Tests.** Concurrent double-accept mints once (real Postgres); concurrent double-purchase cannot
both pass the floor; `agent_runtime` 403 on accept; balances equal the ledger sum after a random
sequence of entries; upkeep for an external task is the flat fee and for an internal task equals
multiplier times recorded cost; migration from `0004` and from empty; the ledger is correct with
no council process ever having run (C9).

**Exit.** Accepting a real twin artifact shows a credit on the Twins page within one poll, the
ledger reconciles to the balance, and no route in the economy calls `session.commit()` (C6).

**Handoff prompt:** as T1, phase L1, branch `feat/ledger-l1-accept-mint`; before opening the PR,
run the `guardian-gatekeeper` agent on the diff and paste its verdict into the PR description.

---

## L2. Materials and workshop

**Goal.** Twins spend credits on things you can see in their room.

**Deliverables.** `world_materials` catalog (seeded, presentational: desk upgrade, shelf, plant,
lamp, wall panel, window, each with a price), `world_builds(tenant_id, agent_id, material_id,
slot, created_at)`, `POST /api/v1/twins/{agent_id}/purchases` (locks the anchor row, checks the
floor, writes `purchase` ledger entry and the build in one transaction), `GET .../builds`; the 3D
room renders builds by slot from `layout.ts` anchors. A twin may buy for itself only; there is no
gifting or trading (ADR-011).

**Tests.** Purchase below the floor is rejected; concurrent purchases serialize; a build renders at
a deterministic slot; `typecheck` and `build`.

**Handoff prompt:** as T1, phase L2, branch `feat/ledger-l2-materials`.

---

## X1. Twin merge / succession (ADR-012)

**Goal.** Two or more proven twins become one successor twin; the predecessors stop existing
operationally while their history and earned credits survive intact. No credit is minted, destroyed
or transferred.

**Deliverables.** `AgentLifecycleState.merged` (terminal: `activate_agent` and `suspend_agent` return
409; mission creation and `_load_external_task` refuse a merged `assigned_agent_id`; the registry
renders no action button). Migration `0007_agent_merges`: `agent_merges(id, tenant_id,
successor_agent_id, decided_by, rationale String(500), idempotency_key unique, approved_at,
created_at)` and `agent_merge_predecessors(merge_id, tenant_id, predecessor_agent_id)` with
`UNIQUE(tenant_id, predecessor_agent_id)` and a composite FK to `agents(tenant_id, id)` (add the
matching unique index on `agents`). `POST /api/v1/agents/merge` behind a router-local role constant
(`operator` / `tenant_admin` / `platform_admin`, 403 for `agent_runtime`), body carries explicit
`predecessor_agent_ids` plus the successor's creation payload; any proposal reference is an opaque
string. Preconditions: predecessors `active` or `suspended`, no task in `queued` / `running` /
`waiting`, successor `agent_code` unused (400, not 500). One transaction: lock every anchor in
ascending `agent_id` order, insert merge rows in `begin_nested()`, create the successor through
`create_agent` (rooms via `ensure_assignment`), flip predecessors to `merged`, `release_assignment`
each, emit `agent.merged` (new `EventType`) per predecessor and for the successor with ids and
counts only. `lineage_head(agent_id)` and a recursive `DISTINCT` depth-capped lineage CTE in the
ledger service; every read, mint and debit resolves the head before locking. `agent_rooms.py`
filters `lifecycle_state IN (draft, active)`.

**Tests.** Merged agent absent from `GET /agent-rooms` and holds no active assignment after the
call; 409 on activate and suspend of a merged agent; 409 when a predecessor has an open task; 422
for a body naming only a proposal reference; 403 for `agent_runtime`; duplicate execute with the
same idempotency key returns the first result, without it the second is 409; chained merge A+B→C
then C+D→E gives `balance(E)` equal to the sum over A, B, C, D, E to the cent; concurrent purchase
against predecessor and successor lets exactly one succeed; `rationale` never appears in
`audit_events.payload`; `downgrade()` from `0007` lists agents left in `merged`.

**Exit criteria.** ADR-012 conditions M1 to M10 each have a named test; typecheck and build green;
the completion report's twin section states that successor balances include lineage.

**Handoff prompt:** as T1, phase X1, branch `feat/twins-x1-merge`, read `docs/adr/ADR-012-twin-merge.md`
first and treat its "Gate Review Outcome" findings as the acceptance list.

---

## C1. Council: reports and proposals

**Goal.** A weekly, restartable, proposal-only routine that reads structured data and leaves a
paper trail, chaired by Fable 5.1.

**Deliverables.**

- `docs/council/PROTOCOL.md`: the four-voice council (Architect, Skeptic, Pragmatist, Critic) plus
  the guardians, the inputs allowed (event types, timestamps, ids, enumerated fields, ledger rows,
  aggregate review stats; never `error`/`reason` strings, never review free text: D1, D2), the
  outputs (`docs/council/YYYY-MM-DD-report.md`, proposal PRs, ledger append), the per-run token
  budget (O4) and the rule that a run that exceeds it stops and reports.
- `scripts/council_snapshot.py`: builds the structured input bundle through an `auditor`-role
  credential (C9) with the new hard max on `list_audit_events(limit)`.
- A scheduled routine (Claude scheduled task, weekly, off by default) that runs the protocol; the
  routine's own prompt lives in `docs/council/ROUTINE_PROMPT.md`.
- First standing agenda items: Gate E report, hook-loss reconciliation (reaped tasks versus closed
  tasks), acceptance-rate by persona, upkeep versus mint by persona, proposals.
- Data-warden sign-off recorded in the ledger before the routine is allowed to push (D5).

**Tests.** The snapshot script is unit-tested to reject any free-form string field; a dry run
produces a report from the local stack without pushing.

**Handoff prompt:** as T1, phase C1, branch `feat/council-c1-protocol`; run the
`guardian-data-warden` agent on the snapshot script's output shape and paste the verdict.

---

## M1. Operator model

**Goal.** Twins can read how the operator works, from sources the operator wrote or explicitly
signaled, and nothing else.

**Deliverables.** Migration `0006_artifact_reviews` (tenant_id, artifact_id, reviewer_id,
decision, rating 1..5 nullable, feedback text nullable, created_at, updated_at, deleted_at;
**not** append-only, operator may edit or delete their own rows, D4); L1's accept/reject writes
here and the rating is optional; `docs/operator/README.md` (tracked) plus `working-style.md.example`,
`review-style.md.example`, `standing-constraints.md.example` (tracked) and their real files
gitignored (D3), with the forbidden-content list in the README; a `knowledge_read` source that
serves the operator docs to twins read-only; the persona system prompt template references it.

**Tests.** Review rows are editable and deletable by their author only; free text never appears in
any event payload; a twin's prompt assembly includes the profile when present and degrades cleanly
when absent.

**Handoff prompt:** as T1, phase M1, branch `feat/operator-m1-reviews-profile`.

---

## A1. Autonomy graduation proposals

**Goal.** Promotion is earned in evidence and granted by a human.

**Deliverables.** `scripts/promotion_eligibility.py` computing, per persona, accepted artifacts in
the window, rejection rate, P1/P2 incidents (from the incident directory), reaped tasks, and
producing a proposal document that lists what could not be verified; a council agenda item that
attaches an adversarial second read of a sample of accepted artifacts by a different model; the
`agent.activated` event payload extended with `previous_autonomy_level` and `autonomy_level`
(C10); the Agent Registry page shows the level with the "advisory for external agents" label.

**Tests.** Eligibility is deterministic on a fixture; the event payload carries both levels;
promotion is impossible through any route other than create-version then activate.

**Handoff prompt:** as T1, phase A1, branch `feat/autonomy-a1-proposals`.

---

## Continuous improvement loop (how the phases keep improving after A1)

1. Weekly council run (C1) reads the structured snapshot and writes the report.
2. The chair (Fable 5.1) turns the report's findings into at most three proposals, each an ADR
   draft or a PR, ranked by operator value and risk, with a gatekeeper verdict attached.
3. The operator reads, comments, and either says "merge it", asks for a change, or declines. Every
   outcome is appended to the ledger.
4. Approved proposals become the next Sonnet 5 handoffs, written in the same shape as the phases
   above (goal, deliverables, tests, exit, prompt).
5. Once a quarter the council re-reads this plan and ADR-011 against the code as it is, and
   proposes retiring anything the evidence says was decoration.

## What this program will never claim

- That an external agent's cost, tool use or diligence was measured. It was declared.
- That an accepted artifact was correct. It was accepted by one person, and the ledger says who.
- That a promoted twin is safe at A3 outside the platform's worker. The label says advisory.
- That the council changed anything. It proposed; a human merged.

## Risks the council asked to keep visible

- Sparse reward: if the operator reviews rarely, the ledger and the promotion signal starve. The
  Twins page shows "unreviewed artifacts" first so review is the path of least resistance.
- Single evaluator drift: ratings alone never gate promotion; the adversarial second read and the
  incident record are required inputs.
- Polling load: 3-second polling scales with the roster; the roster is capped and opt-in, and push
  (SSE over the existing Redis stream) is the deferred ADR-010 Phase E if it ever matters.
- Patience: T1 to T4 are governance plumbing with a visible payoff only at T4. The chair should
  sequence T4's visual demo early in each report so the operator sees the twins moving.
