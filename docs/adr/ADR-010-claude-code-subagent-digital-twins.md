# ADR-010: Claude Code Subagents as Governed Digital Twins

Status: Gate corrections accepted by the operator (Chiew Sin Kwang, 2026-09-15). The
"Gate Review Outcome" section below is the authoritative Phase A design. C1
(`external_agents.py` hardening ships as its own PR, before Phase A, not bundled into it)
and C6 (Mission titles carry repo name + session id only, no prompt text) are both
confirmed. Cleared for implementation planning, subject to `guardian-security-sentinel`
review of the API-key design (C2) and `guardian-data-warden` sign-off on C6 before Phase A
merges, as the ADR already requires.

## Context

Operator objective (Chiew Sin Kwang, 2026-09-14): every agent that Claude Code spins up
under `chiew.sk@daythree.com` must exist as a registered platform agent, the platform
should mirror it as a digital twin that behaves according to its configured setup, and
the 3D world needs the infrastructure to let that twin operate.

What exists today (established by a code-explorer research pass):

- The only Claude Code integration is `scripts/report_claude_status.sh`, fired by
  `UserPromptSubmit` and `Stop` in `.claude/settings.local.json`. It PUTs `working`/`done`
  to `PUT /api/v1/external-agents/{name}/status`, which writes `external_agent_statuses`
  only. That table is by design outside governance: no FK to `agents`, no `audit_events`,
  no budget or permission checks, and the endpoint has no role check or rate limit (a
  CRITICAL gap [ADR-009](ADR-009-agent-room-assignment.md) flagged but did not fix).
- A governed `Agent` row `AGT-CLAUDE-CODE` (`runtime_adapter="external_manual"`, A3) is
  seeded but connected to the status rows only by a matching name string. No `Task` is
  ever created for Claude Code activity, so nothing it does reaches the audit trail.
- `Agent` is a persistent role; `AgentVersion` is its immutable config. Neither models a
  running process. The platform's existing "run" concept is `Task` (under a `Mission`),
  and `complete-external`/`fail-external` in `services/api/routes/tasks.py` already exist
  for closing tasks assigned to non-`custom_durable` agents with real audit events.
- Subagent-level hooks (`SubagentStart`/`SubagentStop`) are not wired. Only the top-level
  session reports.
- ADR-009 (accepted, not yet built) gives rooms to `agents` rows only and excludes
  `external_agent_statuses`. Its plan derives room activity from
  `tasks.assigned_agent_id` + `tasks.status`, lazily backfills room assignments on the
  read path, and polls at 3s.

The objective reduces to: make Claude Code subagents first-class `agents` rows with real
`Task` rows, so ADR-009's existing room and activity machinery renders them without any
special casing.

## Options Considered

**Identity linkage:** (1) one shared `AGT-CLAUDE-CODE` row for all subagents — collapses
every subagent into one persona/autonomy level/tool policy, no real "behaves as per its
setup". (2) one `agents` row per distinct subagent persona/type, spawns as `Task` rows —
bounded room count, each persona's `AgentVersion` reflects its real autonomy/tool policy.
(3) one `agents` row per spawn — faithful to "any agent spun up" but no delete route
exists, turning the room pool into a churn log.

**Live-instance concept:** (a) reuse `Task` directly — but `Task` has no tenant_id and no
external-correlation column, so a `SubagentStop` hook can't find the task to close
without an ALTER. (b) additive `agent_runtime_sessions` table, tenant-scoped, FK to
`agents.id` and nullable FK to `tasks.id`, carrying `external_session_ref`/
`external_instance_ref` for idempotent hook retries.

**Lifecycle signal carrier:** (a) extend `external_agent_statuses` — stays ungoverned by
its own docstring, would require retrofitting audit/FK/role checks onto a table ADR-009
just excluded from scope. (b) `Mission`/`Task` + existing `complete-external`/
`fail-external` routes — already emits the right audit events, already feeds ADR-009's
activity query, already tenant-scoped through `Mission`.

**Hook credential:** (a) current pattern — operator's full-privilege password in a
gitignored script, exchanged per hook fire; scaling this to more hook events exercises
the full admin credential on every subagent spawn. (b) scoped service credential — a
per-operator API key bound to a new `agent_runtime` role limited to the runtime-session
and `-external` task endpoints, revocable independently of the human login.

**Push vs poll:** (a) keep the existing 3s REST polling. (b) add SSE fed from the
existing best-effort Redis `XADD` in `EventPublisher`. Deferred — polling is sufficient
for subagent-lifetime granularity (seconds to minutes); push is only worth it if
tool-call-level mirroring is approved later, which is out of scope here.

## Decision

Option 2 (persona-per-type, spawn-per-`Task`) plus the additive `agent_runtime_sessions`
table, lifecycle carried through `Mission`/`Task`, a scoped `agent_runtime` service
credential, and REST polling retained. Resolved scope, per operator decision
(2026-09-14):

- **Every subagent spawn is in scope**, including untyped/ad hoc `Task`-tool spawns,
  bucketed under a generic `AGT-CC-GENERAL` persona when no named type matches
  `~/.claude/agents`.
- **Personas auto-activate on first sight**: a newly-seen persona (e.g. first time
  "architect" is spawned) is created `active` and immediately gets a room via the
  existing `ensure_assignment` path, capped at a per-tenant persona limit (default 25) to
  bound runaway creation.
- **Persona config comes from a server-side registry**, not from the hook. The hook
  reports "I am type X"; the server looks up X's `autonomy_level`/`tool_policy`. The hook
  can never elevate its own permissions by self-reporting frontmatter.
- **The existing `external_agents.py` status endpoint gets hardened in this same phase**
  (role check + rate limit added to `PUT /{name}/status`), since the new `agent_runtime`
  role model touches the same auth code anyway.

Persona rows are owned by the operator account: `created_by` is the user id behind
`chiew.sk@daythree.com`; the hook never sends an identity claim, the server derives
tenant and owner from the credential (guardian charter rule 3).

### Registration trigger and server-side behaviour

| Claude Code hook | Platform call | Server-side effect |
|---|---|---|
| `SessionStart` | `POST /api/v1/agent-runtime/sessions` (kind=session) | Ensure `AGT-CLAUDE-CODE` active; create `Mission` (idempotent on session id); open runtime session row; audit `mission.created`. |
| `SubagentStart` | `POST /api/v1/agent-runtime/sessions` (kind=subagent, agent_type, parent session id) | Ensure persona `agents` row + `AgentVersion` from the server registry (idempotent on `agent_code`); create `Task` under the session's `Mission`, `assigned_agent_id` = persona, status `running`; open runtime session row; audit `task.created`/`task.assigned`/`task.started`; call ADR-009 `ensure_assignment` for the persona (exception-contained, per the rooms plan). |
| `SubagentStop` | `POST /api/v1/tasks/{id}/complete-external` or `fail-external` | Closes the `Task` and runtime session; audit `task.completed`/`task.failed`. Exact outcome field to be verified against the installed Claude Code hook payload schema in Phase C. |
| `Stop` (top-level) | `PATCH /api/v1/agent-runtime/sessions/{id}` heartbeat/idle | Mission stays open until `SessionEnd`; twin returns to idle. |
| `SessionEnd` | `PATCH .../sessions/{id}` ended | Close Mission; fail any still-open subagent tasks as `abandoned`. A server-side reaper on stale `last_heartbeat_at` also runs, since hooks exit 0 on failure and a killed terminal never fires `SessionEnd`. |
| `UserPromptSubmit` / `Stop` | existing `report_claude_status.sh` | Kept unchanged as a presence-only fallback during migration; deprecated in Phase D. |

Individual tool calls (`PreToolUse`/`PostToolUse`) are **not** mirrored as platform
events — at hook granularity they would produce hundreds of REST calls per session and
drown `audit_events`. A per-task tool-call counter in the `SubagentStop` payload is
enough for the twin.

### 3D world integration

Because personas are `agents` rows and spawns are `Task` rows, ADR-009's activity table
(`queued`→walk, `running`→working, `completed`/`failed`→ring then idle) already produces
the twin's behaviour with no special-casing. Two presentation-only additions to the rooms
plan:

- A room may have several concurrent `Task` rows for one persona (e.g. two parallel
  code-review subagents). Show an occupancy count on the room status panel; avatar state
  follows the latest non-terminal task as the rooms plan already specifies.
- The top-level `AGT-CLAUDE-CODE` room shows the open `Mission` title (session cwd + a
  short prompt summary — see D6 below on privacy) so sessions are distinguishable.

## Phasing

Extends ADR-009; does not modify it. Phases A-C have no dependency on the rooms plan and
can be built in parallel with rooms Phases 1-3. Phase D requires rooms Phases 1-4
complete. Recommended order: rooms Phase 1-2 (schema + allocator) first, since Phase A's
registration endpoint calls `ensure_assignment`; if rooms slips, Phase A ships with that
call behind a feature flag.

**Phase A — identity and registration (backend only).** Additive migration
`0004_agent_runtime_sessions`. New `agent_runtime` role and API-key issuance for the
operator. `POST`/`PATCH /api/v1/agent-runtime/sessions` with role check, rate limit,
idempotency, persona cap. Persona upsert from the server-side persona registry. Harden
`external_agents.py`'s `PUT /{name}/status` (role check + rate limit) in this same phase.
Tests: cross-tenant isolation, idempotent replay, cap enforcement, registration survives
allocator exception (reusing the rooms plan's R2 regression test pattern).
Exit: a scoped-key call creates a persona row, a Mission and a Task, all visible in
`audit_events`.

**Phase B — lifecycle closure and reaper.** `SubagentStop` → `complete-external`/
`fail-external`, extending the allowed-role set to include `agent_runtime` (not weakening
the existing check). Server-side stale-session reaper on `last_heartbeat_at`.
`SessionEnd` closes the Mission.
Exit: every Task opened in Phase A reaches a terminal state within the reaper window even
if the terminal is killed.

**Phase C — hook wiring.** Wire `SessionStart`, `SubagentStart`, `SubagentStop`,
`SessionEnd` in `.claude/settings.local.json` to a new script using the scoped API key
(never the admin password), keeping the exit-0 contract and logging failures locally.
Existing `report_claude_status.sh` untouched. Validate real hook payload field names
against the installed Claude Code version before committing the mapping.
Exit: a real session with two spawned subagents produces one Mission, two closed Tasks,
correct persona rows, and no plaintext password in any new script.

**Phase D — 3D world.** Depends on rooms Phase 4. Add occupancy count and Mission title
to the rooms envelope/panel. Deprecate the `UserPromptSubmit`/`Stop` status hook.
Exit: spawning a subagent makes its persona walk to its room desk within one poll
interval and return to idle on stop.

**Phase E (optional, separate ADR):** SSE over the existing Redis stream, tool-level
events.

Guardian gates: `guardian-gatekeeper` review before Phase A; `guardian-security-sentinel`
review of the API-key design and rate limits before Phase A merges; `guardian-data-warden`
review of what the hook payload sends (prompt text and cwd are potentially sensitive).

## Rationale

Persona-per-type is the only option where "behave as per the digital twin in the setup"
has concrete meaning — each persona's `AgentVersion` carries the autonomy/tool policy the
platform's existing budget/permission logic already enforces, rather than every subagent
sharing one undifferentiated identity. Server-side config (not hook-sent frontmatter)
keeps the hook from being able to self-elevate. Routing lifecycle through `Mission`/`Task`
reuses machinery that already produces correct audit events and already feeds ADR-009's
room-activity query, instead of retrofitting governance onto a table explicitly designed
to not carry it.

## Consequences

- Two simultaneous same-type subagents (e.g. two `architect` spawns) share one room and
  one autonomy level; shown as an occupancy count rather than separate rooms. If
  per-instance rooms are wanted later, `agent_runtime_sessions` already holds the
  instance id, so the room occupant key can switch to it without a schema change.
- Auto-activation is capped per tenant (default 25 personas) specifically so a malformed
  or hostile hook cannot flood `agents` or the room pool — this is the same class of
  capacity-DoS concern ADR-009 blocked on originally, now addressed by construction.
- The scoped `agent_runtime` credential must be issued and rotatable independently of the
  operator's admin login — Phase A cannot ship with the current plaintext-admin-password
  pattern extended to more hook events.
- `external_agents.py` gains a role check and rate limit as part of Phase A, closing the
  gap ADR-009 left open, rather than leaving it a second separate remediation.

## Open Decisions (not yet resolved by the operator)

- **D4 — Instance retention.** Keep `agent_runtime_sessions` rows indefinitely as audit
  context (recommended), or purge after N days?
- **D5 — Concurrent same-persona visual.** Occupancy count on one shared room
  (recommended, stated above) versus per-instance rooms keyed by `external_instance_ref`.
- **D6 — Payload privacy.** Mission title includes prompt text, or only repo name plus a
  hash? Recommend repo name plus a 120-character summary, subject to
  `guardian-data-warden` review before Phase C ships.
- **D8 — Reaper window.** Stale-heartbeat threshold before an open subagent Task is
  auto-failed as abandoned. Recommend 10 minutes.

## Gate Review Outcome (guardian-gatekeeper, 2026-09-14)

Verdict: **BLOCK + ALTERNATIVE**. Four blocking defects found by reading the design
against the actual current code (`services/api/routes/tasks.py`, the mission/task state
machine, `auth.py`, `models.py`). None of them reopen the operator's resolved scope
decisions — each has a fix that preserves persona-per-type identity, the additive table,
the scoped credential, and REST polling. Full review: cross-tenant isolation holds
throughout (the 404-not-403 Mission-join discipline is untouched); the problems are in
lifecycle-closure mechanics, cap concurrency, and blast radius of the new credential.

**B1 — Tasks must be created `queued`, not `running`.** `running -> running` is not a
valid transition (`mission_engine/states/transitions.py`), so `complete-external` would
409 on every close. Fix: `SubagentStart` creates the Task `queued`; the close call drives
`queued -> running -> completed`. This also gives the twin its `queued` = "walking to
desk" state under ADR-009's activity table instead of spawning already `working`.

**B2 — Do not route subagent closure through `complete-external`/`fail-external`.** Both
routes terminate the whole **Mission**, not just the Task, and require a full
`MissionOutput` document plus an object-storage artifact commit per call. A session with
parallel subagents (the operator's own standing instruction to launch agents in parallel
makes this the normal case) would have its Mission completed by the first subagent to
finish, permanently 409-ing every subsequent subagent's close — a Task stuck `running`
forever, a twin stuck "working" in its room forever, and a `mission.completed` audit
event written while work was still open.
Fix: add a dedicated `POST /api/v1/agent-runtime/sessions/{id}/close` in the new router.
It closes only the Task and the runtime-session row, emits `task.completed`/
`task.failed` through the existing `EventPublisher`, and never touches the Mission. The
Mission reaches its terminal state exactly once, at `SessionEnd` or via the reaper.
`services/api/routes/tasks.py` is not modified by this feature at all.

**B3 — Dissolved by B2.** The original design's "extend `complete-external`/
`fail-external`'s allowed roles" would have added `agent_runtime` to a shared `MUTATORS`
constant also used by unrelated mutations (`retry_task`, and identically-named constants
in `missions.py`/`agents.py`), and `_load_external_task` has no ownership check beyond
tenant — so the hook credential could complete/fail *any* task in its tenant, including a
human operator's own mission. Not touching `tasks.py` (per B2) removes this path
entirely.

**B4 — The 25-persona cap must be enforced atomically, not by count-then-insert.**
Concurrent `SubagentStart` calls under the naive design can each count 24 and each
insert, exceeding the cap the same way ADR-009 refused to allow for rooms. Fix, matching
the rooms pattern already accepted: a slot table
`agent_runtime_persona_slots(tenant_id, slot)` with a unique index on `(tenant_id,
slot)`, slots 0-24 — insert the slot row first and let the index be the guarantee.
Persona insert itself uses `ON CONFLICT (tenant_id, agent_code) DO NOTHING` + re-select,
since `uq_agents_tenant_code` would otherwise raise `IntegrityError` on a race between two
first-sights of the same persona type and the request-scoped session rolls back the whole
call on any unhandled exception.

**Conditions folded in as corrections (no operator input needed):**
- C2: API-key issuance is new auth surface, not a shortcut. Add a service `User` row
  (`role='agent_runtime'`, unusable password hash) plus an additive
  `agent_runtime_api_keys` table (`sha256(secret)`, `revoked_at`). A dependency resolves
  the key to that user so `require_role`/tenant scoping work unchanged everywhere else.
  Secret shown once at issuance, never logged. `guardian-security-sentinel` reviews
  before merge.
- C3: number the migration `0003_agent_runtime_sessions` (not `0004`) with
  `down_revision = "0002_external_agent_statuses"`, and make rooms Phase 1-2 (schema +
  allocator) a hard prerequisite of Phase A rather than an optional parallel track — Phase
  A's registration path calls `ensure_assignment`. Apply the same index-sweep-after-
  `create_all` fix the rooms plan uses (R1), with an `indexdef` assertion in tests.
- C4: runtime-generated Missions need a `source`/`kind` discriminator so Mission
  Control's Start/Cancel actions don't operate on them — clicking Start on a session
  Mission with no `assigned_agent_id` would 500 (`tasks.assigned_agent_id` is NOT NULL);
  clicking Cancel would trigger B2's closure trap. Default: hide Start/Cancel for
  `source='agent_runtime'` missions in the UI; they close only via the new endpoint,
  `SessionEnd`, or the reaper.
- C5: `mission_code` is globally unique across tenants (`models.py`), not tenant-scoped —
  use the session UUID directly as the code, never a human-readable scheme like repo+date
  which can collide across tenants.
- C7: the persona registry must create-or-resolve a `model_policy_id` per tenant (it's a
  NOT NULL FK and today only seeded for one tenant) and must set
  `AgentVersion.runtime_adapter = "external_manual"` explicitly — the schema default is
  `"custom_durable"`, which would make every task of a persona created via the default
  permanently unclosable.

**Pending operator confirmation:**
- **C1 — Ship the `external_agents.py` hardening separately, before Phase A, not bundled
  into it.** Two reasons: it's the one non-additive change in this ADR (its rollback is a
  code revert, not a migration downgrade), and this repo has **no rate-limiting
  infrastructure at all** today (checked — no `slowapi`, no limiter middleware). "Add a
  rate limit" means introducing a mechanism (a Redis counter or app middleware), which is
  a platform-level decision worth its own small, reviewable PR rather than being buried
  inside a five-phase feature. This changes the earlier "yes, fix it now, same phase"
  answer only on *sequencing* (separate PR, shipped first) — not on whether to fix it.
- **C6 — Mission titles carry no prompt text at all, not even a truncated summary.**
  Tighter than the earlier default (repo name + 120-char summary): once written,
  `missions.title` and `audit_events.payload` are append-only with no redaction path, so
  anything sensitive in a prompt becomes permanent. Recommend repo name + session id
  only. `guardian-data-warden` sign-off required before Phase A merges regardless of
  which the operator picks.

## Rollback Path

Every new table (`agent_runtime_sessions`) and role (`agent_runtime`) is additive; no
existing table gains a column. Rollback drops the new table and revokes the new role
without touching `agents`, `tasks`, `missions`, or `external_agent_statuses`. The
`external_agents.py` hardening (role check + rate limit) is a behavior change on an
existing route and is not automatically reversible by a migration downgrade — its
rollback is a code revert, called out explicitly since it's the one non-additive change
in this ADR.
