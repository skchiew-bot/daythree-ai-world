# Daythree AI World — Phase 0

[![CI](https://github.com/skchiew-bot/daythree-ai-world/actions/workflows/ci.yml/badge.svg)](https://github.com/skchiew-bot/daythree-ai-world/actions/workflows/ci.yml)

Foundation & walking skeleton for a durable, governed, auditable digital-agent runtime. Phase 0 proves
one loop end-to-end:

> Create Agent → Assign Mission → Execute Task → Produce Artifact → Record Events → Preserve State →
> Recover After Restart → Enforce Permissions → Produce Audit Trail

See [`docs/architecture/PHASE_0_BUILD_SPEC.md`](docs/architecture/PHASE_0_BUILD_SPEC.md) for the full
build contract this repository implements, and
[`PHASE_0_COMPLETION_REPORT.md`](PHASE_0_COMPLETION_REPORT.md) for what was actually delivered, tested,
and left open.

## Quickstart

```bash
cp .env.example .env
make install          # python deps + admin-web npm deps
docker compose up -d --build
make migrate
make seed              # seed tenant, admin user, model policy, Atlas agent
make demo              # runs the Phase 0 demonstration mission end-to-end
```

Admin UI: http://localhost:5173 (login with `SEED_ADMIN_EMAIL` / `SEED_ADMIN_PASSWORD` from `.env`)
API docs (OpenAPI): http://localhost:8000/docs
Grafana: http://localhost:3001 (anonymous viewer enabled for Phase 0)

Without Docker running, you can still run the pure-domain unit test suite:

```bash
pip install -r requirements.txt
make test-unit             # full unit suite, coverage over the whole repo (informational)
make test-coverage-core    # spec §27's actual gate: >=80% on permission evaluator, budget
                            # evaluator, state transitions, event builder, runtime adapter,
                            # model gateway, output validator — currently ~97%
```

`make` isn't installed by default on Windows. If you don't have it (via WSL, Git Bash + a
`make` package, `choco install make`, etc.), run the command each target wraps directly —
e.g. `test-coverage-core` is just the `pytest ... --cov=... --cov-fail-under=80` invocation
in the `Makefile`.

## CI

`.github/workflows/ci.yml` runs on every push/PR to `main` (plus manual dispatch), and all four
jobs are required status checks on `main`'s branch protection — none of them can be skipped to
merge:

| Job | What it proves |
|---|---|
| `unit` | Full unit suite + the spec §27 80%-core-domain-coverage gate |
| `integration-and-security` | TC-P0-001/003/004/010/011/012/013 etc. against a real, throwaway Postgres (testcontainers — no compose stack needed) |
| `frontend` | Admin web type-checks and builds |
| `e2e-and-resilience` | Brings up the **entire** `docker-compose.yml` stack, seeds it, runs the spec §19 demo mission, the spec §27 Playwright journey, and the TC-P0-006/007 container-kill resilience tests |

`e2e-and-resilience` adds a few minutes to every PR, but it's the job that has actually found every
real bug in this codebase so far — see the ADRs for each one — so it's required rather than
main-only.

`main` is branch-protected: all four jobs above are required status checks (with "require branches
to be up to date" on), force pushes and branch deletion are disabled, and `enforce_admins` is on —
so even the repo owner pushes through a PR, not directly to `main`. This PR is the first one opened
after that was turned on, specifically to prove the required-checks gate actually blocks a merge
until all four jobs are green.

## Repository layout

```
apps/admin-web/        React + TypeScript admin UI (5 Phase 0 pages)
services/api/           FastAPI app: auth, agent registry, missions, tasks, artifacts, audit, health
services/mission-engine/state machine, task execution, idempotency, budget enforcement
services/agent-runtime/ AgentRuntimeAdapter protocol + the Phase 0 durable adapter + checkpoints
services/model-gateway/ ModelProvider protocol, mock + Anthropic providers, telemetry
services/event-service/ event envelope publisher: DB audit writer + Redis Stream broadcaster
services/artifact-service/ object storage (MinIO/S3), metadata, hashing, versioning
services/observability/ structlog + OpenTelemetry + Prometheus wiring shared by api/worker
services/worker/        native asyncio worker that actually executes queued tasks
packages/contracts/     IDs, enums, event envelope schema, shared API DTOs
packages/common/        cross-cutting utilities (config, hashing, clock)
packages/policy-sdk/    permission evaluator + budget evaluator (pure domain logic)
packages/tool-sdk/      the 4 Phase 0 tools + the allow/deny registry
infrastructure/         Dockerfiles, compose fragments, Alembic migrations, seed/demo scripts
docs/adr/               8 Architecture Decision Records
tests/                  integration, e2e, resilience, security suites
```

## Why one `requirements.txt` instead of 8 per-service packages

Every backend service in Phase 0 runs from the same Python interpreter and the same dependency set;
splitting into 8 installable packages would add packaging overhead with no isolation benefit at this
scale. Each service is still a clearly separated Python package (importable independently, no
service reaches into another's internals — only through the documented protocols in
`services/model-gateway` and `services/agent-runtime`). Because several service directory names use
hyphens per the build spec (`mission-engine`, `agent-runtime`, …) and Python import names cannot
contain hyphens, each hyphenated service exposes its importable package as an inner underscored
directory (e.g. `services/mission-engine/mission_engine/`). `pyproject.toml`'s `pythonpath` and each
Dockerfile's `PYTHONPATH` put every package/service root on the import path — no `pip install -e`
step is required. This is documented as a pragmatic Phase 0 choice; a real multi-package build
(setuptools/uv workspaces) is reasonable once services are deployed independently.

## Known Phase 0 limitations

- **No LLM API key required.** The demonstration mission runs against `MockModelProvider` by default.
  Set `ANTHROPIC_API_KEY` in `.env` and `DEFAULT_MODEL_PROVIDER=anthropic` to exercise the real
  provider adapter.
- **Runtime adapter is a custom durable state machine, not LangGraph** — see `docs/adr/ADR-004-agent-runtime-adapter.md`.
  Swapping in LangGraph later only requires a new class satisfying `AgentRuntimeAdapter`.
- **Worker is a native asyncio loop, not Celery/Dramatiq** — see `docs/adr/ADR-003-event-transport.md`
  and the worker's own module docstring.
- Some integration/E2E/resilience tests require Docker (Postgres/Redis/MinIO); see
  `PHASE_0_COMPLETION_REPORT.md` for exactly which ones ran in the environment this was built in.
