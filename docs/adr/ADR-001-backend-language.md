# ADR-001: Backend Language & Framework

## Context

Phase 0 needs an async-native backend that can hold an HTTP API, a background worker, and
several internal service boundaries (mission engine, agent runtime, model gateway, event
service, artifact service) without those boundaries becoming an operational burden (8
separate deployable services, 8 sets of CI, 8 dependency trees) before there is any real
need to deploy them independently.

## Options Considered

1. **Python 3.12 + FastAPI + SQLAlchemy 2.x async**, one shared virtual environment across
   all services/packages.
2. **Node.js/TypeScript** (NestJS or Fastify) end-to-end, sharing types with the React
   admin UI.
3. **Go** for the backend services, React for the UI.
4. Python, but as 8 independently-versioned installable packages (`pip install -e .` per
   service) from day one.

## Decision

Python 3.12 + FastAPI + SQLAlchemy 2.x (async) + Pydantic v2, exactly as spec §6
prescribes, with **one shared `requirements.txt`** and **one shared PYTHONPATH-based
import scheme** rather than 8 installable packages (see `README.md`'s "Why one
requirements.txt" section for the exact mechanics — hyphenated service directories per
spec §7 expose an inner underscored Python package, e.g. `services/mission-engine/
mission_engine/`).

## Rationale

- FastAPI + Pydantic v2 gives automatic OpenAPI generation (spec §16 hard requirement)
  and first-class async support, which every downstream service (mission engine, worker)
  needs anyway for non-blocking I/O against Postgres/Redis/MinIO.
- Python's `Protocol` (PEP 544) is exactly the mechanism spec §10/§11 need for the
  `AgentRuntimeAdapter` and `ModelProvider` interfaces — structural typing without a
  runtime dependency on the "real" implementation.
- A single environment/PYTHONPATH is a Phase 0-scale decision, not a permanent one: each
  service is still a self-contained Python package with a clean import boundary (nothing
  reaches into another service's internals except through the two protocols above and
  the shared `packages/contracts` DTOs) — splitting into independently-installable/
  independently-deployable packages later is a packaging change, not a redesign.
- TypeScript end-to-end (option 2) was rejected because it would fragment the
  SQLAlchemy-based domain model spec §8 assumes, and Go (option 3) was rejected because
  it has materially weaker LLM-provider SDK support than Python for the model gateway.

## Consequences

- **Async SQLAlchemy + FastAPI response models need an explicit `session.refresh(obj)`
  before returning any ORM object that was mutated (not just freshly inserted) and has
  a `server_default`/`onupdate`-computed column** (e.g. `updated_at`). FastAPI's
  response-model serialization runs in a sync context; if such a column's value isn't
  already loaded, SQLAlchemy's async engine can't perform the implicit lazy-load and
  raises `MissingGreenlet` instead. Found by CI's first real run of `POST /api/v1/
  agents` (an INSERT immediately followed by an UPDATE in the same request) — fixed in
  the three `services/api/routes/agents.py` routes with this exact pattern
  (`create_agent`, `activate_agent`, `suspend_agent`).
- Local dev requires one `pip install -r requirements.txt`, not per-service installs.
- A future Phase 1+ decision to split a service into its own deployable unit (e.g. the
  model gateway, if it needs independent scaling) requires adding a `pyproject.toml` to
  that service and pinning its own dependency subset — straightforward, not a rewrite.
- Docker images (`infrastructure/docker/*.Dockerfile`) currently copy the *whole*
  `packages/` + `services/` tree into every image rather than just what that image needs;
  acceptable at Phase 0's image-size scale, worth revisiting before Phase 1 if image
  build times become a problem.

## Rollback Path

Revert to per-service `pyproject.toml` files and `pip install -e packages/... services/...`;
no application code changes are required since every service already only imports its own
package plus `packages/contracts`, `packages/common`, `packages/policy-sdk`, and (for the
worker) `packages/tool-sdk` — the exact set a real install boundary would enforce anyway.
