# ADR-011: Digital Twin Program

Status: **Accepted for planning** (2026-09-18). Council convened, gate review folded in, data-warden
conditions folded in. No implementation has started. The executable plan is
`docs/architecture/DIGITAL_TWIN_PROGRAM_BUILD_PLAN.md`; this ADR records *what* was decided and *why*.

## Context

Operator intent (Chiew Sin Kwang, 2026-09-18, verbatim): "create a digital twin for all my claude
agents. the digital twin function is to solve the real world (my world) tasks and projects while
earning in the digital world which the digital twin can use to buy materials to build its digital
world. Spin a council to slowly developed the digital world and digital twin to learn and solve my
real world challenges and build the solutions for my real world to earn and pay for the digital world
expenses by the digital twin ... rerun a continuous improvement council and leverage on Fable 5.1 to
enhance the reliability and improved knowledge and understand how I work ... continuous improvement
loop to achieve operational excellence and autonomous."

What exists today (Phase 0 plus PRs #7 to #17, all merged and CI-verified):

- Governed loop: `agents` / immutable `agent_versions` (with `autonomy_level` A1..A3 and
  `tool_policy`), `missions`, `tasks`, `artifacts`, append-only `audit_events`, per-call
  `model_invocations.estimated_cost`. Budget and permission evaluators enforce limits for agents the
  platform's own worker runs (`runtime_adapter="custom_durable"`).
- One Claude Code session is already a governed agent (`AGT-CLAUDE-CODE`, `external_manual`); it
  closes tasks through `POST /tasks/{id}/complete-external`, which validates output and commits a
  real artifact plus the same audit events the internal path emits.
- The 3D world gives every governed agent a room in a per-tenant apartment (ADR-009) and shows any
  external process that pings the status feed (rate-limited and role-gated since PR #14).
- ADR-010 (accepted, unbuilt) already designs twins for Claude Code agents: one governed agent per
  agent *type* (persona), one Task per spawn under a per-session Mission, `SessionStart` /
  `SubagentStart` / `SubagentStop` / `SessionEnd` hooks, a scoped `agent_runtime` credential, a
  server-side persona registry, a per-tenant persona cap.
- The operator has 73 agent definitions in `~/.claude/agents`, so "all my claude agents" means up
  to 73 personas.

What the platform cannot know, and this ADR refuses to pretend otherwise (the "honesty over
plumbing" precedent from PR #10): it cannot observe an external agent's real tool calls, model usage
or cost; hooks exit 0 by design, so a missed report is silent; the operator is the only human source
of judgment about whether real-world work was good.

## Decision

Five parts, sequenced. Parts 2 to 5 start only after the twins in part 1 close real tasks reliably
(Gate E, defined in the build plan).

1. **Twins first, small roster.** Build ADR-010 Phases A to D with two corrections from this gate:
   migrations renumber to `0004_agent_runtime_sessions` (ADR-010's C3 said `0003`, which ADR-009
   has since taken), and the session-close endpoint accepts an optional `output_text` which, when
   present, is validated and committed as a `mission_output` artifact *for that task only*, leaving
   the Mission untouched (ADR-010 B2 still holds). Without this, twin tasks never produce an
   artifact and nothing downstream has anything to review. The initial roster is 5 opt-in personas
   the operator actually delegates to today, not 73; others activate on first sight up to the
   ADR-010 cap of 25.
2. **A contribution ledger, not a market.** Credits are minted by exactly one action: the operator
   (role `operator`/`tenant_admin`/`platform_admin`, never `agent_runtime`) accepting an artifact
   on a real mission. Credits are debited by upkeep and by purchases of digital-world materials.
   Upkeep for `external_manual` agents is a flat declared per-task fee labeled "declared, not
   measured"; for `custom_durable` agents it is a multiplier on the task's real
   `model_invocations.estimated_cost`. Materials are presentational only (rendered in the agent's
   room). Balances are derived from the append-only ledger, never stored. No transfers between
   agents, tenants or humans; no fiat; no external callbacks. A capped negative balance pauses
   purchases only, never task execution. The ledger is keyed to the persona (`agents.id`), so
   wealth persists across ephemeral spawns (the Skeptic's identity gap, resolved by construction).
3. **A standing council that proposes and never acts.** A scheduled Claude routine (weekly, off by
   default until Gate E) reads structured platform data through an `auditor`-role credential and
   writes a dated report plus proposal PRs. Nothing merges, and no data changes, without the
   operator's explicit "merge it" through the existing branch, PR, 4-job CI flow. Fable 5.1 chairs
   (plans, reviews, synthesizes); Sonnet 5 builds from the plan; the existing guardian agents keep
   their charter roles inside every council run.
4. **An operator model built only from explicit signals.** Accept/reject decisions, an optional
   1 to 5 rating, and optional free-text feedback in a new `artifact_reviews` table (separate from
   the audit trail, with an operator-controlled retention policy), plus operator-maintained profile
   documents under `docs/operator/` (real files gitignored, `.example` tracked). Twins read the
   profile through the existing `knowledge_read` tool. No mining of prompts, transcripts, mail or
   files outside the repo.
5. **Autonomy graduation stays human.** Promotion of an agent version from A1 to A2 to A3 happens
   only through the existing create-version then activate flow, by a human. The council may
   *propose* promotion when a threshold holds (accepted artifacts over a window, zero P1/P2
   incidents, an adversarial second read of a sample by a different model) and must say what the
   platform could not verify. A3 for an `external_manual` agent stays labeled advisory.

## Council (2026-09-18)

Convened per the `council` skill: three fresh voices with only the question and platform facts, no
conversation history. Raw positions kept visible on purpose.

**Architect (in-context):** Go, but the economy must be a closed virtual loop minted only on operator
acceptance; twins first, economy second, council third. Biggest risk: gamified noise on a sparse
reward signal.

**Skeptic:** Build ADR-010 alone; the credits system is not an economy (no scarcity, trade or price
discovery) and autonomy earned on unenforceable self-reports is fiction. Surprise: nobody had
specified how twin "wealth" survives ephemeral per-session spawns.

**Pragmatist:** ADR-010 plus the ledger pay off this quarter; the council loop has no signal to learn
from until real missions close. Cap the first slice at 3 to 5 personas. Surprise: 3-second polling
times 73 personas is real load for zero value until there is task volume.

**Critic:** Build ADR-010 only and hold the rest for 90 days of data. Self-reported completion is the
load-bearing lie; silent hook failures plus a currency equal unaudited money creation; a single
tired evaluator makes ratings the Goodhart target without any transcript mining. Surprise: the
risk of "ADR-010 only" is that the operator loses patience and hand-builds the fun part without
the audit instrumentation.

### Verdict

- **Consensus:** twins (ADR-010) first; keep the roster small; the council has nothing to learn from
  until tasks close; minting must never be hook-driven.
- **Strongest dissent:** Skeptic and Critic would not build the ledger at all yet. Accepted in part:
  the ledger is designed now but *starts* only at Gate E, and it is named for what it is (a
  contribution ledger with presentational spend), not a market.
- **Premise check:** the Skeptic challenged the word "economy". The user-facing concepts (credits,
  materials, upkeep) stay because they are what the operator wants to see; the ADR states plainly
  that there is no price discovery and no transfer.
- **Recommendation changed by the council:** roster capped at 5; economy gated on evidence; ratings
  are never the sole promotion input; wealth is keyed to the persona.

## Gate Review Outcome (guardian-gatekeeper, 2026-09-18)

Verdict: **BLOCK + ALTERNATIVE**, scoped to the minting and upkeep mechanics; the other four parts
pass with conditions. Findings, each with the failure path in current code, and the fix adopted:

- **F1 CRITICAL, mint trigger has no source.** ADR-010's B2 close endpoint deliberately commits no
  artifact; `commit_artifact` is only called from `tasks.py::complete_task_external` and the
  worker, so twin tasks produce zero `artifacts` rows and `POST /artifacts/{id}/accept` could
  never fire. *Adopted:* the close endpoint commits an optional per-task `mission_output` artifact
  (decision part 1).
- **F2 HIGH, upkeep denominator is zero.** `ModelInvocation` rows come only from
  `task_executor.py::_record_model_invocation`; `external_manual` agents never enter the executor.
  *Adopted:* flat declared fee is the sole upkeep path for external agents (part 2).
- **F3 HIGH, double-mint race.** Check-then-insert under `get_db_session`'s commit-on-return lets
  two concurrent accepts both mint. *Adopted:* unique index on `(tenant_id, source_kind,
  source_ref)`, insert inside `begin_nested()`, `IntegrityError` resolved by re-select, the pattern
  at `artifact_service/service.py` lines 83 to 92, plus a concurrent double-accept test.
- **F4 HIGH, lost update on spend.** No route in the repo uses `SELECT ... FOR UPDATE`; a stored
  balance loses concurrent debits and a `SUM()` alone lets two purchases both pass the debt floor.
  *Adopted:* derived balances plus one locked anchor row per `(tenant_id, agent_id)` inside the
  purchase transaction, plus a concurrent double-purchase test.
- **F5 MEDIUM, phantom stream events.** `EventPublisher.publish` does `xadd` before commit, so a
  rolled-back mint still broadcasts. *Adopted:* balances and council inputs read
  `twin_ledger_entries` and `audit_events` only, never the Redis stream.
- **F6 MEDIUM.** Never copy `external_agents.py`'s in-route `session.commit()` into ledger routes.
- **F7 HIGH, hook-credential blast radius.** `require_role` correctly excludes `agent_runtime` from
  accept, but every `get_current_user`-only read route (agent list, task read, presigned artifact
  download) is open to it, and ADR-011 makes artifacts economically meaningful. *Adopted:* accept
  route uses a router-local role constant with a 403 test for `agent_runtime`; ADR-010 Phase A
  narrows `agent_runtime`'s read scope before the ledger ships.
- **F8 MEDIUM, migration numbering.** `0003_agent_room_assignments` is merged. *Adopted:* ADR-010
  becomes `0004_agent_runtime_sessions`, this ADR `0005_twin_economy`; each `downgrade()` drops only
  its own tables, sweeps its own indexes, and is tested from the prior revision.
- **F9 MEDIUM, council read path.** `AUDIT_READERS` excludes `operator`; `list_audit_events` has no
  upper bound on `limit`. *Adopted:* the council uses an `auditor` credential; a hard max on
  `limit`; the ledger must be provably correct with the council never running.
- **F10 MEDIUM.** `agent.activated` records only `active_version_id`. *Adopted:* the payload carries
  old and new `autonomy_level`; free-text feedback never enters `audit_events.payload` or titles.

Conditions C1 to C10 map one-to-one onto the fixes above and are restated as exit criteria in the
build plan. The gatekeeper's own charter note: this verdict is recorded here and in
`docs/council/LEDGER.md` before any implementation planning closes.

## Data-warden review (guardian-data-warden, 2026-09-18)

Verdict: **PASS WITH CONDITIONS.** Confirmed in code that `audit_events.payload` already carries raw
`str(exc)` strings (`task_executor.py` lines 114 to 127, `data.reason` / `data.error`), which are
append-only and unvetted. Conditions adopted:

- **D1.** Council prompts and code never pass `artifact_reviews.feedback` verbatim into any file in
  the repo or PR body; council output references feedback by `artifact_id`, rating and aggregate
  counts. Any prose synthesis goes through a code-enforced redaction pass first.
- **D2.** The council reads event types, timestamps, ids and enumerated fields only; free-form
  string payload fields (`error`, `reason`, any unbounded string) are excluded from anything
  AI-visible or pushed until a redaction gate exists.
- **D3.** `docs/operator/*.md` real files are gitignored with tracked `*.example` files, mirroring
  `.claude/settings.local.json.example`. Forbidden content: other people's names or contact
  details, client or customer names, credentials, internal hostnames or paths.
- **D4.** `artifact_reviews` is not part of the append-only audit trail; the operator can edit or
  delete their own feedback rows; this is stated in code and docs so later work never assumes
  append-only there.
- **D5.** Data-warden sign-off is required before any council routine is wired to push to GitHub.

## Consequences

- Four additive migrations over time (`0004` runtime sessions, `0005` ledger and materials, `0006`
  reviews); no existing table gains a column. Rollback per migration drops only its own tables.
- The operator gains three new controls that are the real product of this ADR: accept/reject an
  artifact with a rating, maintain a profile the twins read, and approve or decline council
  proposals. Everything else is instrumentation around those three signals.
- Honesty costs: every screen and report that shows a twin's cost, autonomy or track record must
  carry the "declared, not measured" label wherever the number came from a self-report.
- The economy can be switched off without touching twins: removing `0005` leaves ADR-010 intact.

## Open decisions for the operator

- **O1.** The initial 5-persona roster (default proposal in the build plan: `planner`, `architect`,
  `code-reviewer`, `tdd-guide`, `security-reviewer`).
- **O2.** Gate E thresholds (default proposal: 30 closed twin tasks, 20 operator reviews, measured
  hook-loss rate under 5% over two weeks).
- **O3.** The credit unit's display name (default: "credits").
- **O4.** Council cadence and per-run token budget (default: weekly, hard-capped).
- **O5.** Which real projects the twins work on first (the build plan assumes this repository).

## Rollback Path

Each phase is its own set of PRs behind its own migration. Rolling back a phase is reverting its
PRs and running that migration's `downgrade()`; earlier phases keep working because nothing later
alters an earlier table. Turning the council off is deleting its scheduled routine; the platform is
designed to be provably correct with the council never running.
