# Phase 0 Completion Report

## Executive Summary

Phase 0's walking skeleton is built end-to-end against `docs/architecture/PHASE_0_BUILD_SPEC.md`:
a FastAPI backend (auth, agent registry, missions, tasks, artifacts, audit, health/metrics), a
native asyncio worker executing a durable, checkpointed agent runtime through a provider-agnostic
model gateway, an idempotent mission engine, an event backbone writing to an append-only audit log
and broadcasting to Redis Streams, MinIO-backed artifact storage with signed downloads, a 5-page
React admin UI, structlog/OpenTelemetry/Prometheus/Grafana observability, 8 ADRs, and a
Docker Compose stack for all 9 required services.

**The pure-domain unit suite (62 tests) passes with 97% coverage on exactly the modules spec §27
names for the 80% target** (permission evaluator, budget evaluator, state transitions, event
builder, runtime adapter, model gateway, output validator). **Docker Desktop's daemon was not
running in this build environment**, so the 14 tests requiring a real Postgres/Redis/MinIO or the
full compose stack (integration, security, e2e, resilience) could not be executed — they are
written, they collect cleanly, and they skip with an explicit reason rather than silently passing.
Section "Gate Decision" below states exactly what must be run, and what result is expected, before
this can be called a *verified* (not just *implemented*) Phase 0.

## Build Version

- Repository: `daythree-ai-world`, git-initialized, no commits made yet (left for the operator to
  review and commit).
- Python 3.12.10, Node 24.8.0, Docker 29.6.1 / Compose v5.3.0.
- ~4,715 lines of Python across `packages/` + `services/`; ~1,204 lines of TypeScript/TSX in
  `apps/admin-web/`; 17 test files, 76 test functions (62 unit + 14 Docker-gated).

## Environment

Built and tested on Windows 11 (native Windows Python, not WSL) with Git Bash. Docker Desktop was
installed but its daemon was not running at build time — see "Known Defects" and "Gate Decision."
No `ANTHROPIC_API_KEY` was available in this session; the demonstration path uses
`MockModelProvider` (see `docs/adr/ADR-005-model-gateway.md`).

## Delivered Components

| Component | Location | Status |
|---|---|---|
| Repository bootstrap, Docker Compose, Makefile, `.env.example` | root, `infrastructure/` | Done |
| Shared contracts (IDs, enums, event envelope, DTOs) | `packages/contracts/` | Done, 100% unit-tested |
| DB schema (11 tables) + Alembic migration | `packages/common/db/`, `infrastructure/migrations/` | Written; migration not yet run against a live Postgres (Docker was off) |
| Permission + budget evaluators | `packages/policy-sdk/` | Done, 100% unit-tested |
| Tool registry + 4 Phase 0 tools | `packages/tool-sdk/` | Done, unit-tested |
| Model Gateway (mock + Anthropic providers, retry, circuit breaker, telemetry) | `services/model-gateway/` | Done, unit-tested |
| Event publisher (DB + Redis Stream) | `services/event-service/` | Done, unit-tested |
| Agent Runtime (durable adapter, checkpoints, prompt assembly) | `services/agent-runtime/` | Done, unit-tested (execute + both resume paths) |
| Mission Engine + Worker (state machine, idempotency, task executor, restart recovery) | `services/mission-engine/`, `services/worker/` | Done; exercised by integration tests not yet run |
| Artifact Service (MinIO, idempotent commit, signed URLs) | `services/artifact-service/` | Done; exercised by integration tests not yet run |
| API (all spec §16 routes + dashboard/model-policies/model-invocations extensions) | `services/api/` | Done; auth helpers unit-tested, full flow not yet run |
| Admin Web (5 pages) | `apps/admin-web/` | Done — `npm run build` succeeds, manually smoke-tested in a browser (login page renders and handles an unreachable API gracefully) |
| Observability (structlog, OTel, Prometheus, 1 Grafana dashboard) | `services/observability/`, `infrastructure/compose/` | Done; not yet observed against live traffic |
| Seed script + demo mission runner | `infrastructure/scripts/` | Written; not yet executed (needs Postgres/Redis/MinIO) |
| 8 ADRs | `docs/adr/` | Done |

## Tests

| Test | Result | Evidence |
|---|---|---|
| Unit suite (62 tests: permission evaluator, budget evaluator, tool registry, event builder, output validator, model gateway incl. retry/circuit-breaker, durable adapter incl. both resume paths and the checkpoint-sequencing regression, state transitions, auth helpers, config safety) | **PASS** | `pytest -m unit -q` → `62 passed` |
| Core-domain coverage gate (spec §27's named modules) | **PASS, 97%** (target 80%) | `pytest -m unit --cov=policy_sdk --cov=contracts.events --cov=contracts.output_contract --cov=.../states --cov=.../adapters --cov=model_gateway.gateway --cov=.../routing --cov-fail-under=80` |
| TC-P0-001 Create Agent | Written (integration) | `tests/integration/test_mission_flow.py` — **not executed** (Docker unavailable) |
| TC-P0-002 Agent Versioning | Covered by route logic (`create_agent_version` never mutates an existing row) | Code review only — **not executed** |
| TC-P0-003 Mission Creation | Written (integration) | `test_mission_flow.py::test_full_mission_lifecycle_tc_p0_001_003_004_011` — **not executed** |
| TC-P0-004 Successful Run | Written (integration) | same test — **not executed** |
| TC-P0-005 Unauthorized Tool | **PASS (unit)** | `tool_sdk/tests/test_tool_registry.py::test_unauthorized_tool_is_denied_before_execution_tc_p0_005` + `policy_sdk` equivalent |
| TC-P0-006 API Restart | Written (resilience) | `tests/resilience/test_api_restart.py` — **not executed** (needs the full compose stack up) |
| TC-P0-007 Worker Crash | **PASS (unit, at the runtime-adapter layer)** + written (integration + resilience) | `agent-runtime/tests/test_durable_adapter.py` (both resume paths) — integration/resilience versions **not executed** |
| TC-P0-008 Model Timeout | **PASS (unit)** | `model-gateway/tests/test_model_gateway.py::test_retries_then_succeeds_tc_p0_008` |
| TC-P0-009 Budget Exceeded | **PASS (unit)** | `policy_sdk/tests/test_policy_budgets.py` + `test_model_gateway.py::test_budget_exceeded_blocks_the_call_tc_p0_009` |
| TC-P0-010 Duplicate Start Request | Written (integration) | `test_mission_flow.py::test_duplicate_start_request_creates_only_one_run_tc_p0_010` — **not executed** |
| TC-P0-011 Artifact Traceability | Written (integration) | same file — **not executed** |
| TC-P0-012 Tenant Isolation | Written (security) | `tests/security/test_authz.py::test_cross_tenant_mission_access_returns_404_not_403_tc_p0_012` — **not executed** |
| TC-P0-013 Audit Reconstruction | Written (integration) | `test_mission_flow.py::test_audit_timeline_reconstructs_full_lifecycle_tc_p0_013` — **not executed** |
| E2E journey (spec §27 script) | Written | `tests/e2e/test_phase0_journey.py` — **not executed** |

**To execute everything marked "not executed":**
```bash
docker compose up -d --build
make migrate && make seed
make test-integration   # TC-P0-001/002/003/004/010/011/013
make test-security      # TC-P0-012 + auth/secret-redaction tests
make test-e2e           # spec §27 UI journey
make test-resilience    # TC-P0-006/007 against real containers
```

## Security Results

Implemented: bcrypt password hashing (direct `bcrypt` call, not passlib — see inline comment in
`services/api/dependencies/auth.py` for the passlib/bcrypt-5.x incompatibility this avoided), JWT
bearer auth, role-based route guards (`platform_admin`/`tenant_admin`/`operator` for mutations),
tenant-scoped queries returning 404 (not 403) on cross-tenant access, deny-by-default tool
permissions with "deny always wins" semantics, secrets never logged (no request body or
Authorization header value ever passed to a log call), signed (never public) artifact URLs.

A `security-reviewer` subagent audited the full auth/authz layer and the permission evaluator
before this report was finalized and found four real issues, all fixed in this build (not left
open):

1. **CRITICAL** — `SECRET_KEY`/`OBJECT_STORE_SECRET_KEY` had shippable placeholder defaults with
   nothing stopping a production deployment from silently inheriting them (a known secret would
   let anyone forge a `platform_admin` JWT for any tenant). **Fixed**: `Settings.
   require_safe_for_production()` now raises at API/worker startup if either is still the
   placeholder value and `ENVIRONMENT` isn't `dev` — see `packages/common/tests/
   test_config_safety.py`.
2. **MEDIUM** — `/api/v1/auth/login` returned immediately (no bcrypt work) for a nonexistent
   email but ran a real bcrypt comparison for a wrong password on an existing one, a timing
   side-channel enabling email enumeration. **Fixed**: the route now always runs a bcrypt
   comparison (against a fixed dummy hash when no user exists) before deciding the response.
3. **LOW** — the unauthenticated `/health/ready` endpoint returned raw exception text (potential
   hostnames/driver internals) for DB/Redis failures. **Fixed**: the response now says only
   `"error"`; full detail goes to structured logs instead.
4. **Doc nit** — `contracts/policy.py`'s docstring claimed `"*"` in `deny` always means "deny
   everything," which doesn't match the actual (correct, verified-safe) implementation in
   `policy_sdk/permissions.py`. **Fixed**: docstring corrected to match and cross-reference the
   real semantics, so a future engineer doesn't "fix" the code to match the wrong doc.

The reviewer separately **verified as sound** (no bypass found): the permission evaluator's
`"*"`-in-`deny` semantics, tenant isolation and RBAC across every route, the artifact download
flow's presigned-URL scoping, and that JWT auth always re-checks the DB (a role change/
deactivation takes effect immediately, not just on next token issuance).

Written but **not executed** (Docker unavailable): cross-tenant 404 test, viewer-cannot-mutate
test, invalid-JWT-denied test, password-hash-never-in-response test — all in
`tests/security/test_authz.py`.

A `code-reviewer` subagent independently reviewed the mission engine, artifact idempotency, and
the durable adapter for correctness/race conditions and found one **CRITICAL** bug, fixed before
this report was finalized:

- `DurableAgentRuntimeAdapter.execute()` hardcoded `sequence=1` for its first checkpoint on every
  call. `task_executor.execute_task` calls `execute()` a **second** time on the same `task_id`
  whenever the model's first output fails validation (the one-shot repair re-prompt) — that second
  call tried to insert another `(task_id, sequence=1)` row, violating
  `uq_checkpoints_task_sequence`. Because checkpoint saves commit (see the durability fix above),
  this surfaced as an uncaught `IntegrityError` that left the task stuck `running` forever: every
  resume replayed the same invalid first output, re-entered the repair path, and hit the identical
  collision again — a permanent stall, not a transient failure, on the very first validation
  failure for any task. **Fixed**: `execute()` now derives its starting sequence from the task's
  current highest checkpoint (`checkpoint_store.latest_for_task`) instead of hardcoding `1` — see
  `services/agent-runtime/agent_runtime/adapters/durable_adapter.py` and the new regression test
  `test_execute_called_twice_for_the_same_task_does_not_collide_on_sequence`.

Two **MEDIUM** findings in `mission_engine/engine/mission_service.py::start_mission`'s rare-race
fallback path were also fixed: it could mislabel a pre-existing task as newly-created and
unconditionally re-enqueue it (even if already running/completed), and it treated any
`IntegrityError` on task insert as the expected idempotency race without verifying a matching row
actually existed first (masking unrelated constraint violations behind a confusing
`NoResultFound`). Both are corrected — see the inline comments at that call site.

## Reliability Results

Idempotent mission start (atomic `UPDATE ... WHERE status IN (...)`), idempotent task creation
(unique `idempotency_key`), idempotent artifact commit (unique constraint + `SAVEPOINT`
reconciliation — see `docs/adr/ADR-007-idempotency.md`), worker-restart recovery via a
startup scan for orphaned `running` tasks plus checkpoint-based resume. The resume logic itself
(the two distinguishable crash points — before vs. after the model call) is unit-tested directly;
the full "kill a real worker container mid-task" scenario is written
(`tests/resilience/test_worker_restart.py`) but not executed.

## Auditability Results

Every mission/task/agent/model/tool/artifact/security state change goes through
`contracts.events.build_event` (100% unit-tested) and `EventPublisher.publish`, which durably
writes to the append-only `audit_events` table before attempting a best-effort Redis Stream
broadcast — a Redis failure never blocks the audit write (unit-tested:
`test_redis_failure_does_not_prevent_the_durable_write_spec_15`). The `/missions/{id}/timeline`
endpoint reconstructs full chronological history; verified by code review and by an integration
test (`test_audit_timeline_reconstructs_full_lifecycle_tc_p0_013`) that has not yet been executed.

## Model Usage & Cost

Demonstration path uses `MockModelProvider`: **$0.00 cost, zero external calls**. The real
`AnthropicProvider` is implemented and gated on `ANTHROPIC_API_KEY`; it has not been exercised
against the live Anthropic API in this session (no key was available). Cost accounting
(`model_gateway/telemetry.py`) is unit-tested for the mock provider's $0 path and the retry/
circuit-breaker paths; live pricing accuracy for the Anthropic path is not independently verified.

## Known Defects

**None found in code that was actually executed** (62/62 unit tests pass, no flaky or skipped-
without-reason tests). The following are explicitly **unverified by execution**, not known-broken:

- The Alembic migration has never been run against a live Postgres.
- The full mission→task→artifact flow, idempotency under real concurrency, and audit persistence
  have never been run against a live Postgres/Redis.
- The admin UI has never been exercised against a live API (only its build and an unreachable-API
  error path were manually checked).
- The resilience tests' timing assumption (killing the worker mid-model-call) is unreliable against
  the near-instantaneous `MockModelProvider` — see the caveat comment in
  `tests/resilience/test_worker_restart.py`.
- `docker-compose.yml` runs plain `postgres:16-alpine`, not a pgvector-enabled image (see
  `docs/adr/ADR-002-database.md`) — irrelevant to Phase 0 (no vector columns exist) but relevant to
  Phase 1 readiness.

No P0/P1 defect (per spec §30's definitions) is known to exist in the delivered code.

## Technical Debt

- Single shared `requirements.txt`/PYTHONPATH import scheme instead of 8 installable packages
  (`docs/adr/ADR-001-backend-language.md`) — fine at Phase 0 scale, worth revisiting before any
  service needs independent deployment/scaling.
- Circuit breaker and retry state are in-process, not shared across worker replicas.
- No per-task lease/visibility-timeout on the Redis queue — a hung (not crashed) worker holds its
  task indefinitely.
- `missions.assigned_agent_id` and `artifacts.logical_output_slot` are additions beyond spec §8's
  literal table definitions, documented inline in `packages/common/db/models.py`.
- The admin UI is functionally complete but deliberately unpolished (plain tables/forms, no design
  system) — an explicit scope trade-off agreed with the user for this build, not an oversight.

## Infrastructure Usage

Local only in this session — no cloud infrastructure was provisioned or billed. Docker images were
not built (`docker compose up` was never run, since the daemon was unavailable); Dockerfiles are
written and follow the spec §25 topology (`admin-web`, `api`, `worker`, `postgres`, `redis`,
`minio`, `otel-collector`, `prometheus`, `grafana`).

## Lessons Learned

- **Independent `security-reviewer` and `code-reviewer` subagents, run after self-review, each
  found a real issue self-review missed**: the security review caught a hardcoded-secret-with-no-
  production-guard (CRITICAL), a login timing side-channel (MEDIUM), and a health-endpoint info
  leak (LOW); the code review caught a checkpoint-sequence collision that made the output-repair
  path permanently stall a task (CRITICAL) plus two narrower race-handling gaps in mission start
  (MEDIUM). All are fixed and covered by new tests. The pattern that mattered here: self-review
  caught the *first* durability bug (checkpoints not committing) because it was actively reasoning
  about crash timing; it did not think to ask "what happens the *second* time this function runs
  against the same task" — exactly the question an independent reviewer, coming in fresh, asked.
- **A durability bug was found and fixed during self-review, before any external review ran**: the
  first version of `SqlCheckpointStore.save()` only `flush()`ed instead of `commit()`ing. Since
  `task_executor.execute_task` runs on one session the worker commits only once at the very end,
  a checkpoint written "before the model call" was still sitting in an open transaction — a real
  process crash during the model call would have rolled the checkpoint back too, silently
  defeating the entire crash-recovery mechanism this build's TC-P0-007 tests exist to prove. Fixed
  by committing at each checkpoint save and at two more points in `task_executor.py` (right after
  recording model telemetry, right after committing an artifact) — see `docs/adr/
  ADR-004-agent-runtime-adapter.md`'s Consequences section for exactly which crash window each
  commit closes. This class of bug (unit tests pass because `InMemoryCheckpointStore` has no real
  transaction semantics to get wrong) is exactly why the integration suite existing — even
  unexecuted in this session — matters: it is written to catch this at the SQL layer, and should
  be run before trusting this fix without independent verification.
- Writing the permission-evaluator unit tests immediately after the implementation caught a real
  logic bug within minutes: the first `effective_tool_set` implementation treated the literal
  `"*"` sentinel in a `deny` list as an active denial, which would have made the spec §12 example
  policy (`allow: [...specific tools...], deny: ["*"]`) deny everything it just allowed. Fixed
  before it touched any other module — a concrete case for writing the test alongside (not long
  after) the code it exercises.
- `pytest-cov`'s `--cov=path/to/file.py` silently produces no coverage data for a single-file
  target (no error) — dotted module names (`--cov=contracts.events`) or directories are required.
  Documented in the `Makefile`'s `CORE_DOMAIN_MODULES` comment so it isn't rediscovered the hard
  way again.
- On native Windows Python (not WSL), `PYTHONPATH` must be `;`-joined, not `:`-joined — the
  `Makefile` now builds it via `python -c "os.pathsep.join(...)"` so the same file works
  unmodified on POSIX and Windows.
- `passlib` 1.7.x's bcrypt backend probes `bcrypt.__about__.__version__`, which bcrypt 4.1+/5.x no
  longer exposes — calling `bcrypt` directly sidesteps an abandoned compatibility shim rather than
  pinning to an old, unmaintained `bcrypt` version.

## Gate Decision

**CONTINUE — conditional on the Docker-gated verification pass below.**

Per spec §29, Phase 0 cannot be marked complete while any required check is unverified. Everything
that *could* run in this build environment (the full pure-domain unit suite, targeting exactly
spec §27's named core-domain modules) passed at 97% coverage with zero failures. Nothing that
*should* run only needs more code — the remaining gap is purely "start Docker Desktop and execute
what is already written":

1. `docker compose up -d --build`
2. `make migrate` — confirms "migration scripts work from clean DB" (spec §29)
3. `make seed` — creates the tenant/admin/model policy/Atlas agent
4. `make demo` — runs the spec §19 demonstration mission end-to-end and prints the artifact +
   timeline
5. `make test-integration && make test-security && make test-e2e && make test-resilience`
6. If all of (2)-(5) pass with no P0/P1 defect, Phase 0 is fully verified and ready for the
   management review checklist (spec §35); if anything fails, fix it and re-run this report's
   test table before proceeding to Phase 1.

## Recommendation for Phase 1

Once the Docker-gated verification above passes: proceed to **Phase 1 — Agent Creation Studio**.
Before doing so, resolve the three "Known Defects" items that are Phase-1-relevant (pgvector image
swap, worker task lease mechanism, shared circuit-breaker state) if Phase 1's scope touches them —
none block Phase 0 sign-off, but a couple would compound if left for Phase 2.
