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
| T2 | Twins: lifecycle closure, reaper, SessionEnd (ADR-010 B, corrected; no output stored) | T1 | T1 merged (2026-09-19, #33) |
| T2b | Twins: opt-in subagent output capture (D24..D31) | T2 | before Gate E needs reviewable artifacts |
| T3 | Twins: hook wiring for a 5-persona roster (ADR-010 C, corrected after gate review) | T2 | T2 merged (2026-09-20, #35); payload gate closed (2026-09-20) |
| T4 | Twins in the 3D world (ADR-010 D) | T3 | T3 merged |
| Gate E | Evidence gate | T3 running for two weeks | thresholds in O2 met |
| R0 | Budget enforcement fix (ADR-013, Phase 0 defect) | nothing | now, recommended before T1 |
| W1 | 3D world: detail and idle movement (ADR-013) | nothing | merged 2026-09-19 (#23) |
| P1 | Projects entity and world read (ADR-014) | R0 (migration parent) | R0 merged |
| W2 | Town layout: buildings, hall, roads, commuting (ADR-014) | P1 | merged 2026-09-19 (#29) |
| W3 | Explore the town: walk, follow a twin, minimap (ADR-014) | W2 | now |
| L1 | Contribution ledger: accept/reject, mint, upkeep | Gate E | operator opens Gate E |
| L2 | Materials and workshop (spend, 3D render) | L1 | L1 merged |
| X1 | Twin merge / succession (ADR-012) | L1 | L1 merged, operator answers O6..O9 |
| R1 | R&D metering and visibility (ADR-013) | R0 + L1 | both merged |
| R2 | R&D allowances as reservations (ADR-013) | R1 | R1 merged, operator answers O11..O13 |
| R3 | R&D proposals, human start, knowledge notes (ADR-013) | R2 | R2 merged |
| C1 | Council: reports and proposals | L1 | L1 merged |
| M1 | Operator model: reviews, profile docs, context injection | L1 + R3 | both merged (ADR-013 F6 amendment) |
| R4 | Bounded standing authorization for R&D (ADR-013) | R3 + C1 | R3 has closed 10 missions |
| A1 | Autonomy graduation proposals | C1 + M1 | both merged |

T1 to T4 are the ADR-010 phases with the corrections from ADR-011's gate review applied; where this
document and ADR-010 disagree, this document wins (it is newer and was gated against the code as it
is now).

---

## T1. Twins: identity and registration

Gate-reviewed against main at `b03db74` on 2026-09-19 (guardian-gatekeeper): **BLOCK + ALTERNATIVE**,
findings T1-F1 to T1-F16, all folded in below; recorded in `docs/council/LEDGER.md`. Where this
section and ADR-010 disagree, this section wins.

**Goal.** A scoped credential can register a session and a subagent spawn as governed objects, and
every persona in the roster exists as a governed `agents` row with the right autonomy and tool
policy, without the hook ever being able to elevate itself, reach any other route, or make the
platform's own worker touch a twin task.

**Deliverables.**

1. **Migration `0004_agent_runtime_sessions`**, `down_revision = "0003c_projects"` (the real head;
   record it in the docstring as `0003c` does, and re-point if another migration merges first).
   NEW tables only; no column on any existing table (`create_all(checkfirst=True)` cannot add one,
   tests build schema from models, CI upgrades an empty DB). Explicit per-index sweep after
   `create_all`; `downgrade()` drops only these three tables.
   - `agent_runtime_sessions(id, tenant_id, kind session|subagent, agent_id nullable FK agents,
     mission_id nullable FK missions, task_id nullable FK tasks, external_session_ref,
     external_instance_ref nullable, parent_session_id nullable, started_at, last_heartbeat_at,
     ended_at, outcome)` with partial unique indexes `(tenant_id, external_session_ref) WHERE
     kind='session'` and `(tenant_id, external_instance_ref) WHERE kind='subagent'`. This table is the
     discriminator for "is this an agent-runtime mission" (an EXISTS against it); there is no
     `source` column on `missions` and none is added (T1-F2).
   - `agent_runtime_persona_slots(id, tenant_id, slot, agent_code)` with `UNIQUE(tenant_id, slot)` and
     `UNIQUE(tenant_id, agent_code)`; the slot is claimed before the persona insert; cap 25 (T1-F14).
   - `agent_runtime_api_keys(id, user_id, key_hash unique, label, created_at, expires_at, revoked_at)`.
2. **Credential.** `UserRole.agent_runtime`. One service `User` per tenant: email
   `agent-runtime+{tenant_code}@daythree.local` (per-tenant unique), `password_hash` a real bcrypt hash
   of discarded random bytes (never a literal like "!": `verify_password` would raise and 500 the public
   login route), status active (T1-F8). API key wire format `dtk_<key_id>_<secret>`, secret
   `secrets.token_urlsafe(32)` (256 bits: the only condition under which unsalted sha256 at rest is
   acceptable; say so in the docstring); the resolver looks the row up by `key_id` and compares the
   digest with `hmac.compare_digest`; it rejects revoked, expired, non-active user and non-active
   tenant; revocation is immediate (no cache); rotation is issue-new then revoke-old; the secret is
   printed once to stdout by an issue script, never passed to structlog, and the script refuses a
   non-local `DATABASE_URL` without an explicit flag (T1-F15). A SEPARATE dependency
   `get_agent_runtime_principal` serves the new router only; `get_current_user`, `require_role` and the
   JWT path are not modified (T1-F4).
3. **Default-deny for the credential** (T1-F3). A `forbid_agent_runtime` dependency added at every
   `api_router.include_router(...)` in `services/api/routes/__init__.py` except `health`, `auth` and the
   new agent-runtime router, so any route added later inherits the refusal. This explicitly covers
   `audit.mission_timeline` (whole `audit_events` rows), `artifacts`, `tasks`, `missions`, `agents`,
   `agent_rooms`, `projects`, `model_policies`, `dashboard`, `model_invocations`, `external_agents`,
   `tenant`.
4. **Routes** `POST /api/v1/agent-runtime/sessions` and `PATCH /api/v1/agent-runtime/sessions/{id}`
   (heartbeat, `ended`). The request schema is `extra="forbid"` with exactly `kind`, `agent_type`,
   `external_session_ref`, `external_instance_ref`, `parent_external_session_ref` (T1-F13): no prompt,
   cwd, description, reason, autonomy, tool policy, model policy or agent code is accepted.
   - kind=session: idempotent on `external_session_ref`; creates a Mission with `mission_code` = the
     session uuid, `title = "Claude Code session {uuid}"`, `assigned_agent_id` = `AGT-CLAUDE-CODE`, and
     drives it `draft -> ready -> running` (`transitions.py` forbids `draft -> running`).
   - kind=subagent: resolve the persona from the registry by EXACT allow-list key; unknown names bucket
     to `AGT-CC-GENERAL`; `agent_code` values are constants in the registry and never formatted from hook
     input (T1-F10); a persona that is `suspended` (or, later, `merged`) is a 409, never reactivated. On
     first sight create the `agents` row and `AgentVersion` (`runtime_adapter="external_manual"`,
     autonomy level and tool policy from the registry only) with `model_policy_id` resolved READ-ONLY by
     `(tenant_id, name="claude-code-external")`; absent is a 409 telling the operator to run the
     issue/seed script; the route never creates a `ModelPolicy` (T1-F11). Claim a persona slot; cap
     exhaustion is a 409 with a stable error code and NEVER falls back to `AGT-CC-GENERAL` (T1-F14).
     Create the Task `queued` with `idempotency_key = f"{mission_id}:ar:{external_instance_ref}"`
     (`start_mission` owns `{mission_id}:task:1`), `title` = registry display name plus instance ref,
     `instructions` a fixed constant. Emit `task.created` / `task.assigned` with ids and enumerated
     values only.
   - Every insert runs inside `begin_nested()`; on `IntegrityError` do `await session.rollback()`, re-run
     the handler ONCE, and if the row is still missing re-raise (asyncpg gotcha, see
     `room_assignment.py` lines ~97-109; `Session.rollback()` discards the outer transaction, so
     continuing mid-transaction is unsafe) (T1-F12).
   - Do NOT call `ensure_assignment` inside the registration transaction: its `IntegrityError` branch
     calls `session.rollback()`, which would discard the whole registration (T1-F6). The world read
     already backfills rooms lazily.
   - Fixed-window Redis rate limit per tenant and per key id on both routes (the
     `external_agents.py` pattern); the 61st call in a window is a 429 that creates no rows; size the
     heartbeat limit for the T3 hook cadence (T1-F9).
5. **Mission guards** (T1-F5). `start_mission_route` and `cancel_mission` return 409 for a mission that
   has an `agent_runtime_sessions` row; `MissionResponse` gains a derived `is_agent_runtime` boolean and
   Mission Control hides Start/Cancel for it (cosmetic on top of the real refusal).
6. **Worker guards** (T1-F7). Exclude tasks whose assigned agent's active version is not
   `custom_durable` from `requeue_orphaned_running_tasks` (`services/worker/main.py`) and from R0's
   sweep; `retry_task` returns 409 for such tasks, mirroring `_load_external_task`.
7. **Persona registry** `services/api/persona_registry.py`: initial roster (operator decision O1)
   `planner`, `architect`, `code-reviewer`, `tdd-guide`, `security-reviewer` with constant codes
   (`AGT-CC-PLANNER`, ...), display names, autonomy level and tool policy per ADR-010 (default A1 and
   the most restrictive tool policy unless ADR-010 says otherwise); every other name is opt-in up to
   the cap of 25, bucketing to `AGT-CC-GENERAL`.
8. **Data exposure** (T1-F13, data-warden D1..D5). The storable-field list is exactly the request
   schema; `audit_events.payload` and event `data` carry ids and enumerated values only; no free text
   is stored. Data-warden sign-off is recorded in `docs/council/LEDGER.md` by the chair before merge.

**Tests** (the gatekeeper's acceptance list; RED first):
1. `alembic upgrade head` from empty and from `0003c_projects` on a populated DB (rows in `missions`,
   `tasks`, `agents`), then `downgrade -1` and `upgrade head`; `indexdef` assertions for all new indexes.
2. Cross-tenant: tenant A's key registers a session; tenant B's key gets 404 on that session id.
3. `agent_runtime` gets 403 on every route in `routes/__init__.py` except its own: table-driven over
   the app's route list; explicit 403 on `GET /missions/{id}/timeline`, `/artifacts/{id}/download`,
   `/tasks/{id}`, `/agents`, `/missions`.
4. `POST /auth/login` with the service user's email returns 401, not 500, for a wrong and an empty
   password; two tenants with service users do not make login raise.
5. Idempotent replay: same `external_session_ref` twice yields one Mission and one session row; same
   `external_instance_ref` twice yields one Task; 10 concurrent duplicates of each on real Postgres
   yield one row.
6. Cap: 10 concurrent first-sights of 10 distinct personas at slot 24 give exactly one success and nine
   409s; never more than 25 slot rows.
7. Registration survives an `ensure_assignment` failure and never calls it inside the transaction;
   assert rows by re-query in a fresh session.
8. `POST /missions/{id}/start` and `/cancel` return 409 for an agent-runtime mission; no Task created,
   status unchanged.
9. `POST /tasks/{id}/retry` returns 409 for an `external_manual` task; `requeue_orphaned_running_tasks`
   returns 0 for a twin task forced to `running` with no lease.
10. Persona resolution: `"000001"`, `"../"`, `"AGT-000001"`, 500 chars of unicode all bucket to
    `AGT-CC-GENERAL` and never resolve onto Atlas or `AGT-CLAUDE-CODE`; a suspended persona is 409 and
    stays suspended.
11. Elevation: a body carrying `autonomy_level`, `tool_policy`, `model_policy_id` or `agent_code` is
    422; the created `AgentVersion` matches the registry constants and is `external_manual`.
12. Rate limit: the 61st call in a window is 429 and creates no rows.
13. Exposure: the request model's field set equals the allow-list exactly; every `audit_events.payload`
    the routes write serialises to ids, timestamps and enum values only (recursive check);
    `missions.title` matches `^Claude Code session [0-9a-f-]{36}$`.
14. API key: revoked and expired keys 401 immediately; a key for a disabled user or suspended tenant
    401s; the secret never appears in captured logs.

**Exit.** A scoped-key call creates a persona row, a Mission and a Task visible in `audit_events`; the
runtime credential gets 403 everywhere else (proved by test 3); the worker never touches a twin task
(test 9); the chair has recorded the data-warden sign-off. Note for later phases: `0005`..`0008` chain
by `down_revision` string and each must be re-pointed at the real head at its own merge; CI has no
migration round-trip step, so T1 ships its own migration test; at cap 25 the apartment overflows past
the 5-floor default (harmless at 5 personas, a note for T4).

**Handoff prompt (paste to a Sonnet 5 session in this repo):**

> Implement Phase T1 of `docs/architecture/DIGITAL_TWIN_PROGRAM_BUILD_PLAN.md` exactly as written, on a
> branch `feat/twins-t1-identity`. Read ADR-010 and ADR-011 first; where they disagree, the build plan
> wins. Follow the repo's existing patterns: `get_db_session` commit-on-return (no in-route commits),
> `get_tenant_scoped_or_404`, partial unique indexes as the concurrency guarantee,
> `create_all(checkfirst=True)` plus an index sweep in the migration, tests against testcontainers
> Postgres marked `integration`/`security`, and `pytest.mark.unit` on pure tests. Never paste a secret
> into the chat or a tracked file. Open the PR with a test plan; do not merge.

---

## T2. Twins: lifecycle closure, reaper, SessionEnd

Gate-reviewed against main at `aee368d` on 2026-09-19: guardian-gatekeeper **BLOCK + ALTERNATIVE**
(T2-F1..F11) and guardian-data-warden **PASS WITH CONDITIONS** (D24..D31), both folded in below and
recorded in `docs/council/LEDGER.md`. Operator decisions (2026-09-19): **T2 stores no subagent output**
(output capture is its own phase, T2b); reap window **2 hours**; the reaper's partial index on
`agent_runtime_sessions` is approved; any agent-runtime key in a tenant may close any session in that
tenant (no per-key owner yet). Where this section and ADR-010 disagree, this section wins.

**Goal.** Every twin Task opened in T1 reaches a terminal state, the session's parent Task and Mission
end, silent sessions are reaped without ever mistaking a live subagent for a lost one, and Gate E can
read an honest hook-loss rate. No subagent output is stored.

**Deliverables.**

1. **Migration `0004b_agent_runtime_closures`**, `down_revision = "0004_agent_runtime_sessions"` (keeps
   the reserved `0005`..`0008` names free; record the parent in the docstring). NEW table only, plus one
   index on the T1 table (operator-approved):
   - `agent_runtime_closures(id, tenant_id, runtime_session_id UNIQUE FK agent_runtime_sessions,
     task_id FK tasks, closed_by enum{hook, session_end, reaper}, outcome enum{completed, failed},
     reason_code enum, tool_call_count nullable int, artifact_id nullable FK artifacts, closed_at,
     late_close_at nullable)`. `artifact_id` is always NULL in T2; it exists so T2b needs no ALTER.
   - Partial index on `agent_runtime_sessions` `WHERE ended_at IS NULL` for the reaper.
   - Declare both in `packages/common/db/models.py` so tests build them; explicit per-index sweep after
     `create_all(checkfirst=True)`; `downgrade()` drops exactly the new table and the new index.
   - `TaskStatus` has no `abandoned`; abandoned is `failed` with `reason_code` held on the closure row.
     No ALTER on any existing table.
2. **Close route**, on the agent-runtime router only (T1's `get_agent_runtime_principal`, tenant-scoped,
   cross-tenant is 404): `POST /api/v1/agent-runtime/subagents/{external_instance_ref}/close`
   (resolved by tenant plus T1's partial unique index; the stateless T3 hook only knows the ref), and
   the same handler at `POST /api/v1/agent-runtime/sessions/{id}/close`. Body `extra="forbid"`:
   `outcome` (completed|failed), `reason_code` (enum, see 5), `tool_call_count` (int 0..10000, optional,
   labelled "declared, not measured" wherever shown: D29). There is NO `output_text` and NO free-text
   `reason` field; sending either is a 422 (D28, T2-F2, operator decision). Its own fixed-window rate
   limit bucket.
3. **Shared closure service** `services/api/services/agent_runtime_closure.py` (T2-F5). It takes the
   twin Task `queued -> running -> completed|failed` in one transaction, emits `task.started` and
   `task.completed`/`task.failed` through `EventPublisher` with ids and enum values only, writes the
   closure row, and NEVER touches the Mission and never enqueues work. `services/api/routes/tasks.py`
   and `services/mission-engine/.../recovery.py` are not modified; `complete_task_external`,
   `task_executor` and `recovery` all complete Missions and must not be reused.
4. **Idempotency and races** (T2-F9). Lock the runtime-session row with `SELECT ... FOR UPDATE` first;
   the UNIQUE `runtime_session_id` on the closure table is the backstop; on `IntegrityError`,
   `await session.rollback()` (T1's pattern) then re-read and return the stored result. A second close
   is a no-op returning the first result, including under 10 concurrent duplicates. A close for a ref
   in another session or tenant is 404.
5. **`reason_code`** is a closed enum (D28): `hook_reported`, `session_ended`, `reaped_stale`. It is stored
   as a string column so T2b can add `artifact_rejected` and `artifact_store_unavailable` without an
   ALTER. No free text is stored anywhere (D30).
6. **PATCH hardening** (T2-F6). T1's `PATCH /sessions/{id}` with an outcome on a `kind=subagent` row
   returns 409 ("use /close"); on a `kind=session` row it becomes the SessionEnd path below. A session's
   end state is set once; later PATCHes cannot overwrite it.
7. **SessionEnd** (T2-F7). Ending a session, in one transaction: take the session's parent Task (the one
   T1 created via `start_mission`) `queued|running -> completed`, close every still-open subagent Task
   as `failed` with `closed_by=session_end, reason_code=session_ended`, then take the Mission
   `running -> completed` (a legal transition). A second SessionEnd changes nothing.
8. **Reaper** (T2-F1, D30), in the worker loop next to R0's sweep, restartable, no resident state.
   Staleness = `GREATEST(COALESCE(sub.last_heartbeat_at, sub.started_at), parent.last_heartbeat_at,
   parent.started_at)` older than the window, a named setting `AGENT_RUNTIME_REAP_WINDOW` defaulting to
   **2 hours**. It selects with `FOR UPDATE SKIP LOCKED` and closes with a conditional update, joins only
   through `agent_runtime_sessions`, and carries an explicit guard `runtime_adapter != 'custom_durable'`
   so it never touches a platform-run task. Reaped subagents close as `failed` with `closed_by=reaper,
   reason_code=reaped_stale`. When every subagent of a silent session is closed and the parent is also
   stale, the reaper runs the SessionEnd path for it. Two reapers at once reap each task once.
9. **Late close** (T2-F1). A hook close that arrives after the reaper already closed the task returns
   200, leaves the Task `failed`, and sets `late_close_at` on the closure row.
10. **Hook-loss rate, computed on read** (correction 10): no stored counter. Lost means
    `closed_by='reaper' AND late_close_at IS NULL`; the rate is lost over all subagent closures in the
    Gate E window. Ship a small read function (and, if cheap, an operator-only endpoint behind the
    existing reader roles) that Gate E will use.
11. **World read.** After the result hold passes, each closed twin shows idle in `GET /agent-rooms` and
    `AGT-CLAUDE-CODE` is no longer stuck "assigned".

**Not in T2 (T2b, before Gate E needs reviewable artifacts):** storing subagent output. When built it
must meet data-warden D24..D31: per-tenant opt-in, default OFF (D24); a secret scan that blocks the
artifact on a match and records only an enum (D25); a size cap of 256 KiB (D26); an operator
delete/tombstone route for `mission_output` artifacts (D27); a consent notice before the opt-in is
exposed (D31); validation failure or an object-store outage still closes the Task, with no artifact
and an enum reason, never a 422 (T2-F3, T2-F8); a fixed artifact title, never the validator's error
text.

**Tests** (RED first):
1. Migration `0004b` round-trip from empty and from `0004` on a populated DB; `indexdef` assertions for
   the closure table's unique index and the new partial index.
2. A close emits `task.started` then `task.completed`, writes one closure row, creates no artifact, and
   leaves the Mission `running`.
3. A body carrying `output_text`, `reason` or any extra field is 422; `tool_call_count` outside 0..10000
   is 422.
4. Ten concurrent duplicate closes produce one closure row and one set of events.
5. Cross-tenant close is 404; a ref from another session is 404; the agent-runtime key still gets 403 on
   `tasks.py` routes.
6. The reaper leaves a live subagent that has no heartbeat of its own but a fresh parent heartbeat;
   reaps a stale one; two reapers at once reap it once; never touches a `custom_durable` task.
7. A late close after reaping is 200, leaves the Task `failed`, sets `late_close_at`, and removes it
   from the loss count.
8. SessionEnd closes the parent Task, fails open subagents with `session_ended`, and completes the
   Mission; a second SessionEnd changes nothing.
9. PATCH with an outcome on a subagent is 409; a session's end state cannot be overwritten.
10. Every `audit_events.payload` the new code writes contains only ids and enum values (recursive check).
11. The hook-loss function returns the documented ratio on a fixture of hook, session_end, reaper and
    late-closed rows.
12. After the result hold, `GET /agent-rooms` shows the closed twins idle.

**Exit.** Two parallel subagents in one session produce one Mission, two closed Tasks and no artifacts;
a deliberately silent third is reaped only after the window; SessionEnd completes the Mission; the
hook-loss function reads the result honestly.

**Handoff prompt:** as T1, phase T2, branch `feat/twins-t2-lifecycle`; read this section first and treat
T2-F1..F11 and D28..D30 as the acceptance list; T2 stores no subagent output.

---

## T3. Twins: hook wiring for the roster

Gate-reviewed against main at `aa0179f` on 2026-09-20: guardian-gatekeeper **BLOCK + ALTERNATIVE**
(T3-F1..F20) and guardian-data-warden **PASS WITH CONDITIONS** (D32..D44), both folded in below and
recorded in `docs/council/LEDGER.md`. Operator decisions (2026-09-20): the ended-parent 409 guard on
the merged T1 route is approved; the payload contract is settled docs first, then one key-names-only
capture; the T3 key expires after 90 days. Where this section and ADR-010 disagree, this section wins.

**Goal.** A real Claude Code session and its roster subagents register, heartbeat, close and (as a
backstop) get reaped without any manual call, without the hook ever blocking or slowing Claude Code,
and without any prompt, path, transcript or message text leaving the machine.

**Pre-build gate: the payload contract (T3-F1), CLOSED 2026-09-20.** Field names from the official
hooks documentation, confirmed by a key-names-only capture on Claude Code 2.1.227:

| Event | Fields the script may read | Notes |
|---|---|---|
| SessionStart | `session_id`, `hook_event_name`, `source` (startup, resume, clear, compact, fork) | stdout is injected into context |
| SessionEnd | `session_id`, `reason` (clear, resume, logout, prompt_input_exit, other) | 1.5 s shared budget unless a hook sets a longer `timeout` |
| Stop, UserPromptSubmit | `session_id`, `hook_event_name` only | UserPromptSubmit stdout is injected into context |
| SubagentStart | `session_id`, `agent_id`, `agent_type` | the same `agent_id` appears in SubagentStop |
| SubagentStop | `session_id`, `agent_id`, `agent_type` | carries `last_assistant_message`: never read |

Not read, logged, hashed or forwarded, ever: `prompt`/`user_prompt`, `cwd`, `transcript_path`,
`agent_transcript_path`, `tool_input`, `tool_result`, `last_assistant_message`, `session_title`,
`background_tasks`, `session_crons`, `scratchpad_dir`, `permission_mode` and every other field (D32).
No payload carries a per-subagent tool-call count, so `tool_call_count` is never sent (D39).

**Confirmed by the capture (Claude Code 2.1.227, 2026-09-20, key names and shapes only; evidence in
the ledger):**

- `SubagentStart` and `SubagentStop` carry `agent_id` and `agent_type`. `agent_id` is 17 lowercase
  hex characters, matches `^[A-Za-z0-9._-]{1,64}$` and is identical at start and stop, so it is the
  instance ref; T3-F1's requirement holds and neither fallback is needed. Their `session_id` is the
  parent session's.
- `SessionStart` `source` was observed as `startup` and `clear`; `SessionEnd` `reason` as `clear`
  and `prompt_input_exit`. `resume`, `compact`, `fork`, `logout` and `other` are documented but were
  not observed; `--continue` was not tested, which does not matter because a run is minted at every
  start.
- `/clear` fires `SessionEnd` for the old session and `SessionStart` for a NEW session id in the
  same second, so state is keyed per Claude session id.
- Hooks run in parallel (two parallel subagents fired in the same second), so the state file is
  written atomically (temp file plus rename) and no hook may assume another has finished.
- `Stop` and `UserPromptSubmit` did not fire inside a subagent's own session; no such event carried an
  `agent_id`.
- Hooks added mid-session fired at once (hot-reload works). The final verification still needs a
  fresh session, because `SessionStart` fires only at session start.
- The subagent-spawning tool is named `Agent`. `bash --login -c true` printed 0 bytes on the
  operator's machine.

**Deliverables.**

1. **`.gitignore`, first commit of the PR:** add `.hook-debug/` and `.claude/twin_env.sh` (T3-F5,
   D35, D37). No other file is created before this lands.
2. **Server guard, operator-approved (T3-F2).** `_register_subagent` returns 409 with a stable detail
   (`parent_session_ended`) when a NEW subagent row would be created under a parent whose `ended_at`
   is set. An idempotent replay of an existing `external_instance_ref` returns the stored row. Test
   first. No other server change: the routes, schemas and enums stay as merged.
3. **`scripts/report_twin_lifecycle.sh`** (tracked, secret-free). Header records the Claude Code
   version and the validated field names.
   - **Structure (T3-F6..F9, D32..D36):** `trap 'exit 0' EXIT`, no `set -e`, no `set -x`, no `eval`;
     stdout and stderr redirected to `/dev/null` on every path; stdin read once with `read -r -t 2`,
     CR stripped, refused above 1 MiB, kept in an unexported variable, never written to disk; values
     extracted with class-restricted anchored `sed` (no jq, no python: neither is safe on this
     machine) and re-validated (session id: canonical UUID; ref: `^[A-Za-z0-9._-]{1,64}$`; event name:
     fixed `case`); the body is assembled from validated tokens only; a missing or invalid value means
     no request and one enum log line, never a derived id.
   - **Transport (D36, T3-F14):** curl with its config on stdin (`-K -`, built by `printf`, so the
     key is in no argv or environment), `--connect-timeout 1 --max-time 2`, `--max-redirs 0`,
     `--noproxy '*'` for loopback, `--proto '=http,https'`, status via `-w '%{http_code}'` only; a
     non-loopback `http` base URL makes no call (`insecure_transport`). Hook `timeout: 5` in settings
     (this also lifts SessionEnd's 1.5 s budget).
   - **Config (T3-F15, D37):** sources `$HOME/.daythree/twin_env.sh` (fixed path, never from the
     payload; outside the repo and the Apache web root). No working defaults: base URL and key must
     both be set, else exit 0 with `no_key` logged. Tracked `.claude/twin_env.sh.example` describes the
     file with placeholders that match no key shape.
   - **Log (D35):** `.hook-debug/twin_lifecycle.log`, fixed grammar `UTC event enum-class HTTP-code pid
     [8-char ref prefix]`, about 256 KiB cap by truncation; never a body, header, key, key id, base
     URL, agent type or payload text. Also a per-event failure counter file that Gate E reads next to
     the server-side rate (T3-F4).
4. **Event mapping.**
   - **SessionStart** (startup, resume, clear, fork): mint a run uuid (a fresh canonical UUID; the
     Claude session id is never the platform ref, T3-F2), `POST /sessions` `kind=session` with it as
     `external_session_ref`, store run uuid, runtime session id and last-heartbeat epoch in
     `.hook-debug/twin-state/<session-id>`. `compact` reuses the existing run; with no state file it
     mints one.
   - **SubagentStart:** `POST /sessions` `kind=subagent`, `external_instance_ref` = the validated
     `agent_id`, `parent_external_session_ref` = the run uuid from state, `agent_type` sent only when it
     equals one of the five roster names (`planner`, `architect`, `code-reviewer`, `tdd-guide`,
     `security-reviewer`; the list is a subset of `persona_registry`); anything else is omitted and the
     server buckets to `AGT-CC-GENERAL` (D38). No state file: log a miss and send nothing (never
     register a session from a subagent event, T3-F12). On `409 parent_session_ended`: mint a new run,
     re-register the session, retry this subagent once.
   - **SubagentStop:** `POST /subagents/{agent_id}/close` `outcome=completed`,
     `reason_code=hook_reported`, no `tool_call_count`; "declared, not measured" wherever shown. A 404 is
     a logged miss, never register-then-close (T3-F12).
   - **Stop, UserPromptSubmit:** heartbeat `PATCH /sessions/{runtime id}` with an empty body, at most
     one per 300 s per session (T3-F3), on the `sessions-heartbeat` bucket only, never a re-POST
     (T3-F4).
   - **SessionEnd:** `PATCH /sessions/{runtime id}` `outcome` from a fixed table (clear, resume,
     logout, prompt_input_exit map to `completed`; other maps to `abandoned`; the raw reason is never
     forwarded), then delete the state file.
   - **Response table (T3-F13):** any 4xx is terminal (log, no retry); connection failure or 5xx retry
     once inside the same timeout budget.
5. **`infrastructure/scripts/issue_agent_runtime_key.py`:** add `--expires-in-days` (T3-F18); the
   operator issues the key in a terminal outside Claude Code straight into the key file (D43); the key
   id and expiry go in the ledger, never the secret. The builder issues no key for the live tenant.
6. **`.claude/settings.local.json.example`:** the six hooks (SessionStart, SubagentStart,
   SubagentStop, SessionEnd, Stop, UserPromptSubmit) in PR #13's Windows-safe shape (fully-qualified
   `bash.exe --login`, no backgrounding, no env prefix or key in `command`), `timeout: 5`, and a
   `permissions.deny` Read rule for the key path so a session cannot read the key into context (D37).
   `report_claude_status.sh` stays untouched; `hook_working.sh.example` is relabelled legacy
   presence-only, deleted at T4 (T3-F16).
7. **Known limits stated up front (T3-F19, T3-F20):** builder sessions in isolated worktrees have no
   `settings.local.json` and produce no twins, so Gate E's sample is the operator's own sessions;
   concurrent windows share the per-tenant rate buckets.

**Tests** (RED first; fixtures are synthetic, generated from field names, D41):
1. `-m unit`, subprocess bash, `TWIN_DRY_RUN=1` writes the request it would send to a file, no
   network, no key. Exit 0 and byte-empty stdout for: each event, empty stdin, malformed JSON, 64 KiB
   and 2 MiB of stdin, CRLF, and every internal command forced to fail.
2. Canary payloads: every non-allow-listed field holds a unique token; none appears in the request,
   argv, log, state file, stdout or stderr; a decoy `"session_id"` and `"agent_type"` inside a message
   string change nothing; `../`, quotes, a 65-character ref and a non-UUID session id send nothing or
   only the validated value.
3. The emitted body field set equals the T1/T2 allow-list; a custom `agent_type` canary is absent; a
   `last_assistant_message` containing "error" and "failed" still yields `completed`.
4. State lifecycle: double SessionStart is one run; compact reuses it; resume mints a new one;
   SubagentStart without state sends nothing; ten concurrent hook runs never corrupt the state file
   (atomic write); SessionEnd removes the file. Heartbeat throttle: 20 Stop
   events in 10 s emit at most one PATCH.
5. Response table against a stub: 200/201, 404, 409 (each detail), 422, 429, 500, no listener; the
   ended-parent path re-registers exactly once and never loops.
6. Key hygiene: a curl shim records argv and env; the secret and `dtk_` prefix are absent from both,
   present only on the shim's stdin; the whole `.hook-debug/` tree and test output contain neither.
7. Repo assertions: `git check-ignore -v` matches `.hook-debug/x.json` and the key path;
   `git grep` finds no key-shaped token in tracked files; the fixtures scan finds no `C:\Users`,
   `/Users/`, `/home/`, `.jsonl`, real UUID, e-mail or common secret format.
8. Server (integration, real Postgres): SessionEnd then a new subagent on that run is 409 with no Task
   created; a replay of an already-registered ref is 200; the rest of T1's and T2's suites pass
   unmodified.
9. `-m e2e`, in the existing full-stack job, key issued inside the job and never echoed: SessionStart,
   two SubagentStart, two SubagentStop, SessionEnd give one Mission, closed Tasks, two closures with
   `closed_by=hook`, no artifact, hook-loss 0; a third never-stopped subagent is reaped and a late
   close returns 200 with `late_close_at`; the heartbeat keeps a session out of the reaper; every
   `audit_events.payload` is ids, timestamps and enums; the canaries appear in no table; the key still
   gets 403 on `/missions`, `/tasks/{id}`, `/artifacts/{id}/download` and `/agents`.

**Exit.** One fresh real session with two parallel roster subagents produces one Mission, two closed
Tasks with the correct persona rows, a heartbeat that survives past the throttle, no new file holding
a secret, and the hook printing nothing. The operator records the ledger evidence to PR #13's
standard (a timestamp and row ids the operator never typed by hand; counts, persona codes, HTTP codes
and 8-character ref prefixes only, D44).

**Handoff prompt:** as T1, phase T3, branch `feat/twins-t3-hooks`; read this section first and treat
T3-F1..F20 and D32..D44 as the acceptance list; the payload gate is closed (ledger, 2026-09-20);
the builder issues no key; end the PR description with the request that the operator start a fresh
session.

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
`audit_events.payload`; `downgrade()` from `0007` lists agents left in `merged`. Receipt (ADR-012
decision 9): the response carries `merge_id`, ids, balances before and after, rooms released and
event ids; a forced conservation mismatch rolls the whole merge back; the receipt is reproducible
from `agent_merges`, the ledger and `audit_events` alone.

**Exit criteria.** ADR-012 conditions M1 to M10 each have a named test; typecheck and build green;
the completion report's twin section states that successor balances include lineage.

**Handoff prompt:** as T1, phase X1, branch `feat/twins-x1-merge`, read `docs/adr/ADR-012-twin-merge.md`
first and treat its "Gate Review Outcome" findings as the acceptance list.

---

## R0. Budget enforcement fix (ADR-013, Phase 0 defect)

**Goal.** The per-task `BudgetPolicy` enforces what it says. Today only `max_output_tokens` can fire.

**Deliverables.** `DurableAgentRuntimeAdapter` builds a real `BudgetUsage` from committed
`model_invocations` for the task plus checkpoint history before every call
(`durable_adapter.py:128` currently passes `BudgetUsage()`). `ModelGateway.generate` re-runs
`evaluate_budget` inside the attempt loop with `is_retry=True` and counts a timeout as a billed call
(`gateway.py:59` vs `72-103`). Every failed or timed-out attempt writes a `model_invocations` row
with `status=failed` and the best available cost. `estimate_cost_usd` raises on an unpriced
`(provider, model)`; `_DEFAULT_PRICE` is removed. Index `model_invocations(tenant_id, agent_id,
created_at)` via the ADR-009 migration pattern. **Shipped as its own migration
`0003b_model_invocations_index`** (`down_revision = "0003_agent_room_assignments"`), so 0004 to
0008 stay free for ADR-010/011/012/013; R0 also adds `ix_model_invocations_task_id` for the
per-task usage query, and `0008_twin_rd` no longer carries the `model_invocations` index. Worker
task lease or ownership check so a restarted second worker cannot requeue a task another worker is
executing (`worker/main.py:26-35`, `queue.py`). Price-table entries in `telemetry.py` are verified
against the provider's current public pricing page on the day R0 is built, with source URL and date
in a comment. The operator's provider is OpenAI (ADR-013 O13), so `gpt-4o-mini` and `gpt-4o` are
checked first, and the builder confirms that `openai_provider.py:31` (`max_tokens`) is accepted by
every model the operator will use, switching to `max_completion_tokens` where a model requires it.

**Tests.** A task with `max_model_calls=1` and a provider that times out twice makes exactly one
provider call; `max_model_cost_usd` trips on the second call once the first's cost is committed;
repair execute counts against the same budget; unpriced model raises; failed attempts appear in
`model_invocations`; two workers and one running task produce one provider call. Existing unit and
integration suites stay green.

**Exit.** Completion report's budget section corrected to say what was enforced before and after.
No real provider key is set in `.env` until this phase is merged.

**Handoff prompt:** as T1, phase R0, branch `fix/budget-enforcement-r0`, read ADR-013 "Context"
first; this is a defect fix, keep diffs minimal and do not touch twin code.

---

## W1. 3D world: detail and idle movement (ADR-013)

**Goal.** Idle twins visibly live in the world; the world looks intentional rather than boxed. No new
backend data.

**Deliverables.** An idle behaviour state machine in `apps/admin-web/src/world/` (in room, leave,
corridor walk, lobby dwell, return; seeded per `agent_id` so movement is deterministic across
clients), driven only by `activity` and room from `useAgentRooms`; walking resumes to the room and
snaps on reassignment (ADR-009 behaviour kept). Avatar walk cycle and facing. Lighting (ambient plus
one key light with shadows), materials (procedural or small embedded textures, no external asset
CDN), furniture meshes per room, corridor and lobby geometry in `apartment.ts`, day/night tint from
the local clock. Render payload built from an allow-list (`agent_id`, `display_name`, `activity`,
`floor`, `room_index`); nothing else from the API reaches the scene (data-warden D11).
`prefers-reduced-motion` disables wandering. Performance budget: 60 fps at 25 agents on the
operator's machine, poll interval unchanged at 3 s.

**Tests.** Allow-list field-set test on the render payload builder; state-machine unit tests
(idle wanders, assigned walks home, working stays home, reassignment snaps); `typecheck` and
`build`; screenshots at 375, 768, 1024 and 1440 attached to the PR (ecc web testing rule).

**Exit.** Operator sees idle agents moving in a lit, furnished building; no text beyond display
names appears on avatars or tooltips.

**Handoff prompt:** as T1, phase W1, branch `feat/world-w1-life`, read ADR-013 decision 6 and D11
first; frontend only; rebuild the `admin-web` image to verify (no bind mount).

---

## P1. Projects entity and world read (ADR-014)

**Goal.** The platform knows what a project is, a mission can belong to one, and the world read can
say which building a twin is in, with tenant isolation proven at the database and in the query.

**Deliverables.** Migration `0003c_projects` (`down_revision` = the real head at merge, recorded in
the docstring): `projects(id, tenant_id, code, name, status, created_at)` with `UNIQUE(tenant_id,
code)` and `UNIQUE(tenant_id, id)`; `mission_projects(mission_id PK, tenant_id, project_id,
created_at)` with composite FK `(tenant_id, project_id) -> projects(tenant_id, id)`; explicit
per-index sweep; `downgrade()` drops both tables. `POST /api/v1/projects`, `POST .../{id}/archive`
behind a router-local role constant and the `model_policies.py` fixed-window rate limit; `GET
/api/v1/projects`; validation per ADR-014 decision 2 (code regex and length, name length and
printable check, per-tenant cap of 48 active); `audit_events` `project.created` /
`project.archived` with ids, status and actor only. Mission create/update accept `project_id`
via `get_tenant_scoped_or_404`. `GET /api/v1/agent-rooms`: fix `_latest_task_by_agent` to
`DISTINCT ON (assigned_agent_id) ... ORDER BY assigned_agent_id, created_at DESC, id DESC` with
explicit `Mission.tenant_id` and `Project.tenant_id` filters on the outer query; add `project_id`
per agent under the lifetime contract (non-null only while `assigned`/`working` or inside the
hold window) and a top-level `projects` array (active plus referenced, one query). Admin UI:
a Projects page (list, create with the D14 warning, archive) and a project picker on Create
Mission; `World.tsx` `focusMission.title` and `job_description` cards replaced by allow-listed
fields (D18). `.github/workflows/ci.yml` gains a migration round-trip step (`upgrade head`,
`downgrade -1`, `upgrade head`) against the E2E stack, with the operator's approval recorded in
the PR.

**Tests.** Two tenants with identical `created_at` tasks never see each other's project (security);
a mission cannot link to another tenant's project (409/404 at the API and an IntegrityError at
the DB); the active-task pick is stable across 20 consecutive reads; `project_id` is null once
the hold window passes; archived-but-referenced projects appear in `projects`; cap and rate limit
enforced; migration upgrade from the parent revision on a populated DB (rows in `missions`) and
downgrade back; `audit_events.payload` never contains `name` or `code`.

**Exit.** A mission attached to a project shows that `project_id` on its agent in `/agent-rooms`
while it runs and null afterwards; the two-tenant test is green; the completion report notes the
F3 and F5 fixes.

**Handoff prompt:** as T1, phase P1, branch `feat/projects-p1`, read ADR-014 first and treat its
gate findings F1..F11 and warden D12..D18 as the acceptance list; ask before touching `ci.yml`.

---

## W2. Town layout: buildings, hall, roads, commuting (ADR-014)

**Goal.** The world reads as a small town: a residence, a community hall, one building per
project, roads between them, and twins that commute. Frontend only.

**Deliverables.** In `apps/admin-web/src/world/`: `town.ts` (grid of 48 lots, residence and hall
on the main street, roads as a graph of waypoints), `lots.ts` (stable placement: probe from
`hash(project.id)` in the API's `(created_at, id)` order, first free lot), `buildings.ts`
(procedural project building and hall from primitives; height and footprint from lot and id
only), `commute.ts` (path over the road graph; vehicle from trip distance and `agent_id`: walk,
bicycle, motorbike; walk home when a task ends), vehicle meshes, a `WorldProject = {id, code}`
branded type with its own field-by-field builder, `WorldAgent` gains `project_id`; camera
overview and click-to-focus; signage renders `code` only; `describeScene` stays counts-only;
`prefers-reduced-motion` keeps everyone in place; W1's disposal and allow-list tests extended.
Performance budget unchanged: 60 fps at 25 agents and 20 projects, poll interval 3 s.

**Tests.** Lot placement: adding a project moves no existing lot; 48 distinct lots for 48 projects;
placement keyed on id, unchanged by renaming. Commute: vehicle is a pure function of distance and
id; a twin whose `project_id` becomes null walks home over the graph; reassignment still snaps;
reduced motion disables commuting. Allow-list: raw API rows fail to compile for both agents and
projects; the key sets are exact. Typecheck, build, vitest, screenshots at 375, 768, 1024, 1440.

**Exit.** With real data the operator sees the residence, the hall, one building per active
project and twins commuting on roads; no text beyond codes and display names appears in the
canvas.

**Handoff prompt:** as T1, phase W2, branch `feat/world-w2-town`, read ADR-014 decisions 4 and 5
and D13..D15 first; frontend only; rebuild the `admin-web` image to verify.

---

## W3. Explore the town: walk, follow a twin, minimap (ADR-014)

Operator request (2026-09-19): "I want to be able to explore the town rather than just spinning and
zooming in using the mouse." Operator agreed to walk mode, follow-a-twin and a minimap. Gate-reviewed
before build: guardian-gatekeeper **PASS WITH CONDITIONS** (W3-F1..F8, C1..C9) and guardian-data-warden
**PASS WITH CONDITIONS** (D19..D22), both recorded in `docs/council/LEDGER.md`. Frontend only; no
backend or payload change.

**Goal.** The operator can walk through the town with the keyboard, ride along behind any twin, and
navigate with a minimap, without the existing overview, click-to-focus, wandering or commuting changing.

**Deliverables** (all under `apps/admin-web/src/`):

1. **Explore region and modes.** A focusable explore element (`tabIndex=0`, `role="application"`,
   labelled "Town explorer: WASD or arrows to walk, Shift to run, drag to turn, Esc to return to
   overview"), separate from the `role="img"` canvas node; overlays and the minimap live outside the
   `role="img"` node (W3-F5). Three modes: `fly` (the existing OrbitControls overview and
   click-to-focus), `walk`, `follow`. Mode buttons in the UI; Esc from walk or follow returns to fly.
2. **One camera owner per frame** (W3-F2). Only `fly` calls `rig.update` and `controls.update`.
   Entering walk or follow cancels any rig ease and sets `controls.enabled = false`; returning to fly
   sets `controls.target` first, then re-enables.
3. **Walk mode.** A client-only operator avatar built from the existing avatar primitives with a
   constant seed `"operator"`, no label, and nothing from the signed-in user (D20, C5); it is not a
   governed agent and appears in no payload. WASD/arrows move, Shift runs, drag on the explore element
   turns (`setPointerCapture`, released on `pointerup`/`pointercancel`); NO pointer lock (C3).
   Frame-rate independent. Spring-arm third-person camera that pulls in to avoid clipping walls.
   Collision against axis-aligned footprints from a pure `footprints(projects, lots)` function (lots
   from `buildingSpec(id, lot)` plus `allLotSlots()[i].center`, the hall from
   `HALL_CENTER/HALL_WIDTH/HALL_DEPTH`, the residence from `layout.ts`), computed only when the
   project-set signature changes (W3-F7), clamped to the town bounds. After each town sync, if the
   operator stands inside a footprint (a freed lot was filled by a shifted project), push them out to
   the nearest free edge (W3-F6).
4. **Proximity card.** Within about 3 m of a building's door, an HTML card (outside the canvas) shows
   the project `code` and `status`, and the `display_name` plus `activity` of twins placed there. Code
   and status only, never `name` (D19). `WorldProject` is widened to `{id, code, status}` for this,
   built field by field in `toWorldProject` with the branded-type test updated; the data-warden
   approved `status` (active/archived, non-sensitive) in D19, resolving gate finding W3-F1.
5. **Follow a twin.** Pick a twin in the scene or the sidebar; the camera rides behind it. Twin pick
   proxies use an `agent:` key prefix so they never collide with project ids, `"hall"` or
   `"residence"` (W3-F4). `TownAvatars` gains a read-only `poseOf(agentId, out): boolean` filling a
   caller-owned buffer; when it returns false or the twin is at the residence, follow ends or cuts to
   the residence view, never reading a disposed handle (W3-F3). A small HTML panel shows the twin's
   `display_name`, `activity` and the `code` of its current place only (D19).
6. **Picking by mode** (W3-F4). Building picks apply only in fly mode; in walk and follow modes a
   click selects a twin to follow; a click at the end of a drag never triggers `rig.focus`.
7. **Minimap.** A small top-down 2D canvas in a corner: roads and buildings as geometry with no labels,
   twins as dots, the operator as an arrow with heading (D21). The static layer is drawn once per
   project-set signature on an offscreen canvas; dynamic dots redraw at 10 Hz or less (C6). A hover
   tooltip, if any, shows twin `display_name` and `activity` only (D21). Click teleports in walk mode
   and focuses in fly mode. A text alternative lists building codes, the twin count and the operator's
   current street (C8).
8. **Keyboard scoping** (C1, C2, W3-F8). The ONLY key listener is on the explore element: no `window`
   or `document` listeners; `preventDefault` only for handled keys while it has focus; held keys are
   cleared on `blur`, `visibilitychange`, mode switch and dispose. Listeners are attached inside
   `runWorld` and removed in its dispose (StrictMode mounts twice).
9. **Reduced motion** (C7): follow and teleport use camera cuts; walking stays allowed because the user
   drives it; W1/W2 behaviour under reduced motion is unchanged.
10. **Performance** (C6): no per-frame allocations (scratch vectors and poses allocated once); the
    operator avatar adds 12 draw calls or fewer; 60 fps budget unchanged.
11. **No persistence**: nothing is written to `localStorage` or `sessionStorage` in W3 (the gatekeeper
    excluded it; the stricter of the two reviews applies).

**Tests** (vitest; pure modules without three.js where possible; RED first where testable):
1. Typing in a page input (Login, Projects) moves nothing; keys act only while the explore element has
   focus.
2. Holding W then blurring the window (and a `visibilitychange`) stops the avatar.
3. A StrictMode remount leaves exactly one listener set (count listeners).
4. In walk mode the camera position after a frame equals the spring-arm output (no orbit snap-back).
5. A short click in walk mode does not call `rig.focus`; a drag-end click never does.
6. A followed twin that reaches home or leaves the payload ends follow without error.
7. A lot shift while the operator stands on a freed lot moves them outside all footprints.
8. The proximity card, follow panel and minimap render no project `name`: a fixture with a sentinel
   string in `ProjectSummary.name` never appears in their output; `WorldProject` key set is exactly
   `{id, code, status}` and a raw `ProjectSummary` fails to compile.
9. The operator avatar receives no auth/session field (type-level and a render-props assertion).
10. Footprints and the minimap static layer rebuild only when the project-set signature changes.
11. Collision: the avatar cannot enter any footprint and stays inside the town bounds; movement is
    frame-rate independent.
12. `commute.test`, `townAvatars.test`, `lots.test` and every other existing test pass unmodified.

**Exit.** The operator walks the town, gets a card at each building, follows a twin through a commute,
and navigates by minimap, all by keyboard; fly overview and click-to-focus work exactly as before.

**Out of W3:** building interiors, other operators' presence, sound, server-side or local persistence of
position, pointer lock.

**Handoff prompt:** as T1, phase W3, branch `feat/world-w3-explore`; read this section first and treat
W3-F1..F8, C1..C9 and D19..D22 as the acceptance list; frontend only; CI is authoritative.

---

## R1. R&D metering and visibility (ADR-013)

**Goal.** The operator sees what each twin costs before granting any allowance.

**Deliverables.** Per-twin spend for the current period from `model_invocations` (after R0), a
`purpose` discriminator (`task` | `rd`) on new rows via the `0008` side table
`twin_rd_invocations(invocation_id, mission_id, purpose)`, admin UI panel and room label. For
`external_manual` twins the figure is the declared flat fee (ADR-011 part 2) labeled "declared, not
measured", side by side with measured figures. Review-latency metric (time from artifact commit to
operator accept/reject) added to the Gate E dashboard.

**Tests.** Period sum matches committed rows to the cent; declared and measured never mix in one
number; label present in API and UI. Live smoke test, run by the operator locally with the key in
`.env` (never pasted anywhere): one real OpenAI call capped at a few cents, its recorded
`estimated_cost` compared with OpenAI's own usage dashboard, the difference noted in the PR.

**Handoff prompt:** as T1, phase R1, branch `feat/rd-r1-metering`.

---

## R2. R&D allowances as reservations (ADR-013)

**Goal.** A twin's credits unlock a share of an operator-set ceiling; spend can never exceed it.

**Deliverables.** Migration `0008_twin_rd`: `twin_rd_allowances(tenant_id, agent_id nullable,
period_start, ceiling_usd, bands JSONB, created_by)`, `twin_rd_anchors(tenant_id, agent_id, period,
reserved_usd, spent_usd)` (the locked row), `twin_rd_proposals` (used in R3). Step function
`available_draw(credits) -> share of ceiling` from versioned bands (O12); a unit test asserts the
function is a step function (fewer than 5 distinct outputs over the input range) so it cannot express
a price. Reservation before every R&D call: `SELECT ... FOR UPDATE` on the anchor, debit
`max_model_cost_usd`, true up after the call, fail closed. Credits are never debited.

**Tests.** Concurrent R&D calls against one allowance serialize and the sum never exceeds the
ceiling; a reservation that exceeds remaining allowance is rejected before the provider is called;
true-up never goes negative; zero ceiling blocks the next reservation.

**Handoff prompt:** as T1, phase R2, branch `feat/rd-r2-reservations`, gate findings F4 and the
ADR-011 F4 pattern are the acceptance list.

---

## R3. R&D proposals, human start, knowledge notes (ADR-013)

**Goal.** A twin proposes; a human starts; the worker runs it under the allowance; what it learned
persists and only it can read it.

**Deliverables.** `POST /api/v1/twins/{agent_id}/rd-proposals` (any principal acting as the twin,
including the `agent_runtime` credential once ADR-010 adds it) writes a `draft` proposal row.
`POST .../rd-proposals/{id}/start` behind `MUTATORS` creates a mission assigned to a
`custom_durable` version of the same persona with `BudgetPolicy.max_model_cost_usd` bounded by the
remaining allowance and `risk_level=low`; `external_manual` versions are refused. `ArtifactType.
knowledge_note`. At mission creation the platform queries `artifacts` with
`artifact_type='knowledge_note' AND agent_id=:agent AND tenant_id=:tenant` and injects the notes
into `task.input_context` under a `knowledge` key (data-warden D6); `knowledge_read` is unchanged.
Provider data-handling terms named in `docs/operator/PROVIDER_TERMS.md` before the first non-mock
R&D mission (D8). `runtime_checkpoints` stays off every read path (D9).

**Tests.** A second agent's notes are absent from the first agent's context; an `external_manual`
version cannot start R&D; proposal start requires a human role; the mission's budget never exceeds
remaining allowance; note content never appears in `audit_events.payload`.

**Handoff prompt:** as T1, phase R3, branch `feat/rd-r3-proposals`; gate findings F6, F7, F8 and
warden D6..D10 are the acceptance list.

---

## R4. Bounded standing authorization (ADR-013)

**Goal.** "On their own accord", with recorded human approval granted ahead of time.

**Deliverables.** `twin_rd_authorizations(tenant_id, agent_id, max_missions, max_usd, expires_at,
revoked_at, signed_by)`; an `audit_events` row `rd.authorization_granted` / `revoked`; the worker
starts `draft` proposals against an active authorization without a per-mission click, decrementing
its counters inside the anchor lock. Kill switch: Redis flag `rd:halt:{tenant_id}` checked between
dequeue and execute and before every provider attempt; zeroing a ceiling also sets the flag.

**Tests.** Expired or revoked authorization starts nothing; counters never exceed limits under
concurrency; the halt flag stops the next attempt of an in-flight mission; every grant and
revocation is in `audit_events`.

**Handoff prompt:** as T1, phase R4, branch `feat/rd-r4-authorization`; starts only after R3 has
closed 10 real R&D missions and the operator has reviewed their notes.

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
