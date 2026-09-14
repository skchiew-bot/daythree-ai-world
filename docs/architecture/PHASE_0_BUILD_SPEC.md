# Daythree AI World
## PHASE 0 BUILD SPEC — Foundation & Walking Skeleton
**Version:** 1.0  
**Date:** 14 September 2026  
**Primary Build Target:** Claude Code  
**Status:** Ready for implementation  
**Scope:** Foundation only — no 3D world, no rewards economy, no red team, no production connectors

---

# 1. Phase 0 Objective

Phase 0 exists to prove that Daythree AI World can support a **durable, governed, auditable digital agent runtime** before any advanced world mechanics are introduced.

The Phase 0 objective is to prove this single controlled loop:

> Create Agent → Assign Mission → Execute Task → Produce Artifact → Record Events → Preserve State → Recover After Restart → Enforce Permissions → Produce Audit Trail

The build must demonstrate that an AI agent can be instantiated as a persistent digital employee and can complete a real task while every material action is observable and reconstructable.

Phase 0 is successful only when the system can survive restart, preserve traceability, reject unauthorized actions, and replay the mission history accurately.

---

# 2. Phase 0 Success Criteria

Phase 0 shall be considered complete only when all of the following are proven:

1. A human administrator can create an agent.
2. The agent is stored persistently.
3. The agent can be assigned a mission.
4. The mission is decomposed into at least one task.
5. The task can be executed through an agent runtime.
6. A model call is made through an internal model gateway.
7. The output is stored as a versioned artifact.
8. Every mission state transition emits an event.
9. Every model/tool call is recorded.
10. The runtime can restart without losing the mission.
11. Retry does not create duplicate committed artifacts.
12. Unauthorized tool access is denied.
13. Every artifact can be traced back to:
   - tenant
   - mission
   - task
   - agent
   - agent version
   - runtime version
   - model/provider
   - prompt version
14. Full audit history can be reconstructed.
15. Health, latency, usage, and cost telemetry are available.
16. Automated test suite passes.
17. A `PHASE_0_COMPLETION_REPORT.md` is generated.

---

# 3. Explicitly Out of Scope

Do not build the following in Phase 0:

- 3D world.
- Babylon.js scene.
- houses.
- buildings.
- transport.
- economy.
- XP.
- digital credits.
- red team.
- whistleblowing.
- autonomous investment committee.
- real-world system write access.
- multi-agent collaboration.
- agent self-learning.
- dynamic skill progression.
- voice.
- telephony.
- contact center operations.
- COPC operational automation.
- production DAISY integration.

Interfaces may be created where useful, but implementation must remain focused.

---

# 4. Architecture Principles

## 4.1 Hard Rules

1. **Server is the source of truth.**
2. **Event-driven state changes.**
3. **Every meaningful action is auditable.**
4. **Agent identity is persistent.**
5. **Agent configuration is versioned.**
6. **Prompts are versioned.**
7. **Runtime is replaceable.**
8. **Model provider is replaceable.**
9. **Tool permissions are deny-by-default.**
10. **No credentials in prompts, artifacts, logs, or long-term memory.**
11. **All external side effects require an explicit tool permission.**
12. **All write operations must be idempotent where practical.**
13. **Every task has a budget.**
14. **Every failure is observable.**
15. **No silent fallback.**

---

# 5. Target Phase 0 Architecture

```text
                         ┌──────────────────────┐
                         │     Admin Web UI     │
                         │ React + TypeScript   │
                         └──────────┬───────────┘
                                    │ HTTPS
                                    ▼
┌──────────────────────────────────────────────────────────────┐
│                        FastAPI API                           │
│ Auth | Agent Registry | Mission API | Artifact API | Audit  │
└──────────────┬───────────────────┬───────────────────────────┘
               │                   │
               │                   ▼
               │         ┌─────────────────────┐
               │         │   Mission Engine    │
               │         │ state / checkpoints │
               │         └──────────┬──────────┘
               │                    │
               │                    ▼
               │         ┌─────────────────────┐
               │         │  Agent Runtime      │
               │         │ Runtime Adapter     │
               │         └──────────┬──────────┘
               │                    │
               │                    ▼
               │         ┌─────────────────────┐
               │         │   Model Gateway     │
               │         │ provider abstraction│
               │         └──────────┬──────────┘
               │                    │
               │                    ▼
               │               LLM Provider
               │
               ▼
┌────────────────────────┐
│      PostgreSQL        │
│ core state + pgvector  │
└────────────────────────┘

┌────────────────────────┐
│        Redis           │
│ queues / locks / cache │
│ event stream           │
└────────────────────────┘

┌────────────────────────┐
│    Object Storage      │
│ artifacts / evidence   │
└────────────────────────┘

┌────────────────────────┐
│   OpenTelemetry        │
│ metrics/traces/logs    │
└────────────────────────┘
```

---

# 6. Technology Baseline

## Backend
- Python 3.12+
- FastAPI
- SQLAlchemy 2.x
- Alembic
- Pydantic
- PostgreSQL 16+
- pgvector
- Redis 7+
- Redis Streams
- Celery / Dramatiq / native async worker
- OpenTelemetry
- structlog or equivalent JSON logging

## Frontend
- React
- TypeScript
- Vite or Next.js
- TanStack Query
- React Hook Form
- Zod

## Infrastructure
- Docker
- Docker Compose
- Nginx or Caddy reverse proxy
- S3-compatible object storage
- secret manager or `.env` only for local development

## Testing
- pytest
- pytest-asyncio
- HTTPX
- Playwright
- factory_boy or equivalent
- testcontainers where useful

---

# 7. Repository Structure

```text
daythree-ai-world/
├── apps/
│   └── admin-web/
│       ├── src/
│       ├── tests/
│       └── package.json
│
├── services/
│   ├── api/
│   │   ├── app/
│   │   ├── routes/
│   │   ├── schemas/
│   │   ├── dependencies/
│   │   ├── middleware/
│   │   └── tests/
│   │
│   ├── mission-engine/
│   │   ├── engine/
│   │   ├── states/
│   │   ├── checkpoints/
│   │   └── tests/
│   │
│   ├── agent-runtime/
│   │   ├── adapters/
│   │   ├── runtime/
│   │   ├── prompts/
│   │   └── tests/
│   │
│   ├── model-gateway/
│   │   ├── providers/
│   │   ├── routing/
│   │   ├── telemetry/
│   │   └── tests/
│   │
│   ├── event-service/
│   │   ├── publisher/
│   │   ├── consumers/
│   │   └── tests/
│   │
│   ├── artifact-service/
│   │   ├── storage/
│   │   ├── metadata/
│   │   └── tests/
│   │
│   └── observability/
│       ├── logging/
│       ├── tracing/
│       └── metrics/
│
├── packages/
│   ├── contracts/
│   ├── common/
│   ├── policy-sdk/
│   ├── tool-sdk/
│   └── model-sdk/
│
├── infrastructure/
│   ├── docker/
│   ├── compose/
│   ├── migrations/
│   └── scripts/
│
├── docs/
│   ├── architecture/
│   ├── adr/
│   ├── api/
│   └── runbooks/
│
├── tests/
│   ├── integration/
│   ├── e2e/
│   ├── resilience/
│   └── security/
│
├── .env.example
├── docker-compose.yml
├── Makefile
└── README.md
```

---

# 8. Core Domain Model

## 8.1 Tenant

```sql
tenants
- id UUID PK
- code VARCHAR UNIQUE
- name VARCHAR
- status VARCHAR
- created_at TIMESTAMPTZ
- updated_at TIMESTAMPTZ
```

## 8.2 User

```sql
users
- id UUID PK
- tenant_id UUID FK
- email VARCHAR
- display_name VARCHAR
- role VARCHAR
- status VARCHAR
- created_at TIMESTAMPTZ
- updated_at TIMESTAMPTZ
```

Initial roles:
- `platform_admin`
- `tenant_admin`
- `operator`
- `auditor`
- `viewer`

## 8.3 Agent

```sql
agents
- id UUID PK
- tenant_id UUID FK
- agent_code VARCHAR
- display_name VARCHAR
- description TEXT
- department VARCHAR
- role_name VARCHAR
- lifecycle_state VARCHAR
- active_version_id UUID
- created_by UUID
- created_at TIMESTAMPTZ
- updated_at TIMESTAMPTZ
```

## 8.4 Agent Version

```sql
agent_versions
- id UUID PK
- agent_id UUID FK
- version INTEGER
- system_prompt TEXT
- runtime_adapter VARCHAR
- model_policy_id UUID
- autonomy_level VARCHAR
- tool_policy JSONB
- memory_policy JSONB
- settings JSONB
- checksum VARCHAR
- created_by UUID
- created_at TIMESTAMPTZ
```

No in-place editing.
Any material change creates a new agent version.

## 8.5 Model Policy

```sql
model_policies
- id UUID PK
- tenant_id UUID FK
- name VARCHAR
- primary_provider VARCHAR
- primary_model VARCHAR
- fallback_config JSONB
- max_input_tokens INTEGER
- max_output_tokens INTEGER
- max_cost_per_task NUMERIC
- timeout_seconds INTEGER
- retry_policy JSONB
- created_at TIMESTAMPTZ
```

## 8.6 Mission

```sql
missions
- id UUID PK
- tenant_id UUID FK
- mission_code VARCHAR UNIQUE
- title VARCHAR
- objective TEXT
- requested_by UUID
- status VARCHAR
- priority VARCHAR
- risk_level VARCHAR
- budget_policy JSONB
- created_at TIMESTAMPTZ
- started_at TIMESTAMPTZ
- completed_at TIMESTAMPTZ
```

Mission status:
- draft
- ready
- running
- paused
- failed
- completed
- cancelled

## 8.7 Task

```sql
tasks
- id UUID PK
- mission_id UUID FK
- assigned_agent_id UUID FK
- title VARCHAR
- instructions TEXT
- status VARCHAR
- retry_count INTEGER
- idempotency_key VARCHAR
- budget_policy JSONB
- input_context JSONB
- output_artifact_id UUID
- started_at TIMESTAMPTZ
- completed_at TIMESTAMPTZ
- created_at TIMESTAMPTZ
```

Task status:
- queued
- running
- waiting
- failed
- completed
- cancelled

## 8.8 Runtime Checkpoint

```sql
runtime_checkpoints
- id UUID PK
- mission_id UUID FK
- task_id UUID FK
- agent_id UUID FK
- checkpoint_sequence BIGINT
- state JSONB
- status VARCHAR
- created_at TIMESTAMPTZ
```

## 8.9 Artifact

```sql
artifacts
- id UUID PK
- tenant_id UUID FK
- mission_id UUID FK
- task_id UUID FK
- agent_id UUID FK
- agent_version_id UUID FK
- artifact_type VARCHAR
- title VARCHAR
- storage_uri VARCHAR
- content_hash VARCHAR
- mime_type VARCHAR
- version INTEGER
- metadata JSONB
- created_at TIMESTAMPTZ
```

## 8.10 Audit Event

```sql
audit_events
- id UUID PK
- tenant_id UUID FK
- event_type VARCHAR
- actor_type VARCHAR
- actor_id UUID
- mission_id UUID NULL
- task_id UUID NULL
- agent_id UUID NULL
- correlation_id UUID
- causation_id UUID NULL
- payload JSONB
- occurred_at TIMESTAMPTZ
```

Audit events are append-only.

## 8.11 Model Invocation

```sql
model_invocations
- id UUID PK
- tenant_id UUID FK
- mission_id UUID FK
- task_id UUID FK
- agent_id UUID FK
- provider VARCHAR
- model VARCHAR
- input_tokens INTEGER
- output_tokens INTEGER
- estimated_cost NUMERIC
- latency_ms INTEGER
- status VARCHAR
- request_hash VARCHAR
- response_hash VARCHAR
- created_at TIMESTAMPTZ
```

Do not store secret or raw sensitive payloads here by default.

---

# 9. Event Contract

All major state changes must emit a normalized event.

```json
{
  "event_id": "UUID",
  "event_type": "task.started",
  "event_version": "1.0",
  "occurred_at": "2026-09-14T00:00:00Z",
  "tenant_id": "UUID",
  "correlation_id": "UUID",
  "causation_id": "UUID",
  "actor": {
    "type": "agent",
    "id": "UUID"
  },
  "mission_id": "UUID",
  "task_id": "UUID",
  "agent_id": "UUID",
  "data": {},
  "metadata": {
    "service": "mission-engine",
    "environment": "dev"
  }
}
```

## Phase 0 Required Event Types

### Agent
- `agent.created`
- `agent.version_created`
- `agent.activated`
- `agent.suspended`

### Mission
- `mission.created`
- `mission.started`
- `mission.completed`
- `mission.failed`

### Task
- `task.created`
- `task.assigned`
- `task.started`
- `task.retry_started`
- `task.completed`
- `task.failed`

### Runtime
- `runtime.checkpoint_created`
- `runtime.recovered`

### Model
- `model.requested`
- `model.completed`
- `model.failed`

### Tool
- `tool.requested`
- `tool.denied`
- `tool.completed`
- `tool.failed`

### Artifact
- `artifact.created`
- `artifact.version_created`

### Security
- `authorization.denied`
- `budget.exceeded`

---

# 10. Runtime Adapter Contract

Claude Code must implement an internal interface so the platform never depends directly on one framework.

```python
class AgentRuntimeAdapter(Protocol):
    async def initialize_run(self, context: RunContext) -> RunHandle:
        ...

    async def execute(self, handle: RunHandle) -> RunResult:
        ...

    async def checkpoint(self, handle: RunHandle) -> Checkpoint:
        ...

    async def resume(self, checkpoint: Checkpoint) -> RunResult:
        ...

    async def cancel(self, handle: RunHandle) -> None:
        ...
```

The first adapter may use LangGraph or a custom durable runtime.

No business logic may call LangGraph directly outside the adapter layer.

---

# 11. Model Gateway Contract

```python
class ModelProvider(Protocol):
    async def generate(
        self,
        request: ModelRequest
    ) -> ModelResponse:
        ...
```

Model Gateway responsibilities:

- provider abstraction
- model routing
- retries
- timeout
- token limits
- cost ceiling
- telemetry
- error normalization
- circuit breaker
- request/response hashing
- provider/model version metadata

The Mission Engine must never call OpenAI, Anthropic, Gemini, DeepSeek, or any provider directly.

---

# 12. Tool Permission Model

Phase 0 needs only simple tools:

1. `artifact.write`
2. `artifact.read`
3. `knowledge.read`
4. `calculator.execute`

No arbitrary shell.
No open internet scraping.
No production database access.

Each agent version contains an allowlist:

```json
{
  "allow": [
    "artifact.write",
    "artifact.read",
    "knowledge.read"
  ],
  "deny": [
    "*"
  ]
}
```

Effective access = platform policy ∩ tenant policy ∩ agent policy ∩ mission policy.

Deny always wins.

---

# 13. Mission Execution Flow

```text
1. User creates Mission
2. Mission Engine validates mission
3. One task is created
4. Agent is assigned
5. Permission policy is resolved
6. Budget is resolved
7. Runtime initializes
8. task.started event emitted
9. Prompt/context assembled
10. Model Gateway invoked
11. Model call telemetry stored
12. Output returned
13. Artifact stored
14. Artifact metadata persisted
15. Runtime checkpoint persisted
16. task.completed event emitted
17. mission.completed event emitted
18. Audit timeline available
```

---

# 14. Idempotency Strategy

Required for:
- mission start
- task start
- artifact creation
- model retry
- event publication

Every task receives an `idempotency_key`.

For artifact commit:

```text
unique(
  task_id,
  artifact_type,
  logical_output_slot,
  committed_version
)
```

If worker crashes after artifact storage but before final task update, retry must detect the existing artifact and reconcile instead of creating an uncontrolled duplicate.

---

# 15. Reliability and Recovery

## Required Failure Scenarios

### API restart
Expected:
- no mission loss
- state reloads from DB

### Worker crash during model call
Expected:
- timeout/retry policy
- no duplicate final artifact

### Redis unavailable
Expected:
- event publication retries
- durable DB state remains correct
- service health becomes degraded

### PostgreSQL unavailable
Expected:
- no task continues to commit changes
- no partial success reported

### Model provider timeout
Expected:
- normalized retry
- retry count recorded
- budget checked before retry

### Object storage failure
Expected:
- artifact not marked complete
- task remains retryable

---

# 16. API Specification

## Tenant
`GET /api/v1/tenant`

## Agents
`POST /api/v1/agents`
`GET /api/v1/agents`
`GET /api/v1/agents/{agent_id}`
`POST /api/v1/agents/{agent_id}/versions`
`POST /api/v1/agents/{agent_id}/activate`
`POST /api/v1/agents/{agent_id}/suspend`

## Missions
`POST /api/v1/missions`
`GET /api/v1/missions`
`GET /api/v1/missions/{mission_id}`
`POST /api/v1/missions/{mission_id}/start`
`POST /api/v1/missions/{mission_id}/cancel`

## Tasks
`GET /api/v1/missions/{mission_id}/tasks`
`GET /api/v1/tasks/{task_id}`
`POST /api/v1/tasks/{task_id}/retry`

## Artifacts
`GET /api/v1/missions/{mission_id}/artifacts`
`GET /api/v1/artifacts/{artifact_id}`
`GET /api/v1/artifacts/{artifact_id}/download`

## Audit
`GET /api/v1/missions/{mission_id}/timeline`
`GET /api/v1/audit/events`

## Health
`GET /health/live`
`GET /health/ready`
`GET /metrics`

OpenAPI must be generated automatically.

---

# 17. Admin UI — Phase 0

Only build five pages.

## Page 1 — Dashboard

Show:
- total agents
- active missions
- failed missions
- completed missions
- model calls
- current cost
- system status

## Page 2 — Agent Registry

Columns:
- Agent Code
- Name
- Role
- Department
- Version
- Runtime
- Model Policy
- Status

Actions:
- create
- view
- create version
- activate
- suspend

## Page 3 — Create Agent

Fields:
- name
- description
- department
- role
- system prompt
- runtime adapter
- model policy
- autonomy level
- tool permissions

## Page 4 — Mission Control

Fields:
- title
- objective
- assigned agent
- budget
- priority
- risk level

Actions:
- create
- start
- retry
- cancel

## Page 5 — Mission Detail

Tabs:
- Overview
- Tasks
- Artifact
- Timeline
- Model Usage
- Audit

---

# 18. Seed Agent

Create exactly one mandatory seed agent.

```yaml
agent_code: AGT-000001
display_name: Atlas
department: Research
role_name: Research Analyst
lifecycle_state: active
autonomy_level: A1
runtime_adapter: langgraph
tools:
  - artifact.write
  - artifact.read
  - knowledge.read
```

System instruction:

> You are Atlas, a Daythree AI Labs Research Analyst. Your job is to analyze the assigned requirement using only the information and tools provided. Separate verified facts, assumptions, risks, and recommendations. Never invent evidence. If required information is unavailable, clearly identify the gap. Produce a concise, structured artifact suitable for management review.

---

# 19. Phase 0 Demonstration Mission

Title:

**Research the requirements for an AI-powered repeated-interaction analysis capability**

Objective:

> Produce a concise business and technical requirement note explaining what data, integrations, controls, KPIs, and risks should be considered when analyzing repeated customer interactions across voice and digital channels.

Expected artifact structure:

1. Objective
2. Business problem
3. Required data
4. Core capabilities
5. Integration considerations
6. KPI framework
7. Risks
8. Assumptions
9. Recommended MVP boundary
10. Open questions

The mission does not require any real external connector.

---

# 20. Prompt Assembly

Runtime prompt must be built from components:

```text
SYSTEM BASE POLICY
+
AGENT VERSION PROMPT
+
MISSION OBJECTIVE
+
TASK INSTRUCTIONS
+
TOOL POLICY
+
BUDGET POLICY
+
AVAILABLE CONTEXT
+
OUTPUT CONTRACT
```

All prompt components must be individually versioned or identifiable.

Store:
- prompt template ID
- version
- hash
- assembled prompt hash

Do not blindly store sensitive assembled prompts in logs.

---

# 21. Output Contract

Mission output must validate against a schema.

Example:

```json
{
  "title": "string",
  "executive_summary": "string",
  "sections": [
    {
      "heading": "string",
      "content": "string"
    }
  ],
  "assumptions": ["string"],
  "risks": ["string"],
  "open_questions": ["string"]
}
```

Invalid output triggers one controlled repair attempt.

If repair fails:
- mark task failed
- preserve raw response securely
- emit failure event

---

# 22. Budget Control

Each mission:

```json
{
  "max_model_cost_usd": 2.00,
  "max_model_calls": 6,
  "max_runtime_minutes": 10,
  "max_retries": 2,
  "max_output_tokens": 8000
}
```

Budget enforcement happens before each invocation.

If exceeded:
- reject invocation
- emit `budget.exceeded`
- task enters failed or waiting-for-approval state

---

# 23. Security Requirements

## Authentication
OIDC/OAuth2-ready abstraction.

For local Phase 0:
- local seeded admin account acceptable
- passwords hashed using modern password hashing

## Authorization
Every state-changing endpoint validates:
- authenticated actor
- tenant
- role
- resource scope

## Data Security
- TLS in hosted environment
- secrets outside code
- DB encryption at rest where cloud provider supports
- object storage private
- signed artifact download URLs
- no public buckets

## Logging
Never log:
- API keys
- access tokens
- passwords
- secret headers
- raw credentials

---

# 24. Observability

Every request should carry:
- `request_id`
- `correlation_id`

Every mission:
- `mission_id`

Every agent run:
- `run_id`

Every model invocation:
- `model_invocation_id`

Track at minimum:

### API
- request count
- latency
- status code

### Mission
- missions started
- missions completed
- mission failures
- duration

### Model
- invocation count
- tokens
- cost
- latency
- failures

### Runtime
- task duration
- retries
- checkpoint count
- recovery count

### Infrastructure
- CPU
- RAM
- DB connections
- Redis health
- worker queue depth

---

# 25. Docker Compose Topology

Phase 0 local stack:

```yaml
services:
  admin-web:
  api:
  worker:
  postgres:
  redis:
  minio:
  otel-collector:
  prometheus:
  grafana:
```

Optional:
- Jaeger or Tempo

Do not introduce Kubernetes in Phase 0.

---

# 26. Initial Infrastructure Sizing

## Developer Machine / Local Lab

Recommended:
- 8 CPU cores
- 32 GB RAM
- 100 GB free SSD
- Docker Desktop / Linux Docker
- no GPU required

Minimum workable:
- 4 CPU cores
- 16 GB RAM

## Hosted MVP Sandbox

Start with:
- 8 vCPU
- 32 GB RAM
- 150–250 GB SSD
- managed PostgreSQL if budget permits
- Redis
- S3-compatible storage

The language model remains API-hosted.

Do not buy GPU hardware during Phase 0 unless a separate local-model use case is explicitly approved.

---

# 27. Testing Strategy

## Unit Tests
Required for:
- permission evaluator
- budget evaluator
- state transitions
- event builder
- runtime adapter
- model gateway
- output validator

Target:
- >= 80% coverage for core domain logic

## Integration Tests
- Postgres persistence
- Redis Streams
- object storage
- mission → task → artifact
- model gateway mock provider
- audit event persistence

## End-to-End Tests
Using Playwright:
1. login
2. create agent
3. create mission
4. start mission
5. wait for completion
6. inspect artifact
7. inspect audit timeline

## Security Tests
- cross-tenant access denied
- viewer cannot mutate
- unauthorized tool denied
- secrets redacted
- invalid JWT/session denied

## Resilience Tests
- worker kill
- API restart
- Redis restart
- simulated model timeout
- object store unavailable

---

# 28. Mandatory Phase 0 Test Cases

## TC-P0-001 Create Agent
**Given** administrator  
**When** valid agent created  
**Then** agent and version stored and `agent.created` emitted

## TC-P0-002 Agent Versioning
Modify prompt.
Expected:
- new version
- old version immutable
- active version explicit

## TC-P0-003 Mission Creation
Expected:
- valid mission persists
- mission event emitted

## TC-P0-004 Successful Run
Expected:
- mission complete
- task complete
- artifact generated
- model telemetry stored

## TC-P0-005 Unauthorized Tool
Give Atlas request to use unavailable shell/network tool.
Expected:
- denied
- audit event
- no execution

## TC-P0-006 API Restart
Restart API during queued mission.
Expected:
- state survives

## TC-P0-007 Worker Crash
Kill worker after task start.
Expected:
- task recovered or cleanly retryable
- no duplicate artifact

## TC-P0-008 Model Timeout
Expected:
- retry according to policy
- retry audit
- cost budget honored

## TC-P0-009 Budget Exceeded
Expected:
- next model call blocked
- explicit event

## TC-P0-010 Duplicate Start Request
Submit same mission start twice.
Expected:
- only one run

## TC-P0-011 Artifact Traceability
Expected:
artifact maps to mission/task/agent/version/model invocation.

## TC-P0-012 Tenant Isolation
Attempt cross-tenant fetch.
Expected:
HTTP 403/404 according to policy.

## TC-P0-013 Audit Reconstruction
Given completed mission,
timeline reproduces full lifecycle chronologically.

---

# 29. Acceptance Gate

Claude Code must not mark Phase 0 complete unless:

- all critical test cases pass
- no P0/P1 defect remains open
- migration scripts work from clean DB
- database can be backed up and restored
- one full mission survives restart test
- audit timeline is complete
- unauthorized tool test passes
- token/cost accounting works
- source code contains no committed secret
- README can bring up environment from clean checkout
- completion report exists

---

# 30. Definition of P0 / P1 Defects

## P0 — Critical
- security bypass
- data loss
- cross-tenant exposure
- state corruption
- credentials leak
- task executes unauthorized action

## P1 — High
- mission cannot complete
- artifact cannot be retrieved
- retry causes duplicate material side effect
- audit trail materially incomplete
- cost/budget control bypassed

Phase 0 cannot exit with open P0/P1 defects.

---

# 31. Claude Code Work Order

Claude Code should execute in this order.

## STEP 1 — Repository Bootstrap
Create repository structure.

Deliver:
- folder layout
- README
- Docker Compose
- `.env.example`
- Makefile

## STEP 2 — Database
Implement:
- schema
- migrations
- seed tenant
- seed admin
- seed model policy
- seed Atlas

## STEP 3 — Shared Contracts
Implement:
- IDs
- enums
- event schema
- API DTOs

## STEP 4 — API
Implement:
- health
- auth
- agent registry
- missions
- tasks
- artifacts
- audit

## STEP 5 — Event Service
Implement:
- event publisher
- DB audit writer
- Redis stream publishing

## STEP 6 — Model Gateway
Implement:
- interface
- one production provider adapter
- mock provider for tests
- cost and token telemetry
- retry/timeout

## STEP 7 — Runtime Adapter
Implement:
- runtime protocol
- first adapter
- checkpoints
- recovery

## STEP 8 — Mission Engine
Implement:
- mission state machine
- task execution
- idempotency
- budgets

## STEP 9 — Artifact Service
Implement:
- object storage
- metadata
- hashes
- versioning

## STEP 10 — Admin Web
Implement five Phase 0 pages.

## STEP 11 — Observability
Implement:
- JSON logs
- tracing
- metrics
- dashboards

## STEP 12 — Tests
Implement all mandatory tests.

## STEP 13 — Recovery Test
Prove recovery during active mission.

## STEP 14 — Phase Completion Report
Generate:
`PHASE_0_COMPLETION_REPORT.md`

---

# 32. Required Architecture Decision Records

Claude Code must generate:

- `ADR-001-backend-language.md`
- `ADR-002-database.md`
- `ADR-003-event-transport.md`
- `ADR-004-agent-runtime-adapter.md`
- `ADR-005-model-gateway.md`
- `ADR-006-object-storage.md`
- `ADR-007-idempotency.md`
- `ADR-008-observability.md`

Each ADR:
- context
- options
- decision
- rationale
- consequences
- rollback path

---

# 33. Completion Report Template

```markdown
# Phase 0 Completion Report

## Executive Summary

## Build Version

## Environment

## Delivered Components

## Tests
| Test | Result | Evidence |

## Security Results

## Reliability Results

## Auditability Results

## Model Usage & Cost

## Known Defects

## Technical Debt

## Infrastructure Usage

## Lessons Learned

## Gate Decision
- STOP
- FIX
- CONTINUE

## Recommendation for Phase 1
```

---

# 34. Handover Prompt for Claude Code

Use the following instruction when starting implementation:

> You are the lead platform engineering team for Daythree AI World. Build only Phase 0 from `PHASE_0_BUILD_SPEC.md`. Treat the document as the canonical implementation contract. Before coding, review the entire specification and generate the required Architecture Decision Records. Do not expand scope into the 3D world, economy, red team, or Phase 1 features. Implement using modular interfaces so runtime, model provider, event transport, and storage can later be replaced. All state-changing behavior must be auditable, permissions must be deny-by-default, and mission execution must survive service restart. Build test-first for the critical domain logic. At the end, run the complete Phase 0 test suite and generate `PHASE_0_COMPLETION_REPORT.md`. Do not declare completion while any P0/P1 defect remains open.

---

# 35. Management Review Checklist

Before approving Phase 1, management should ask:

1. Can we create an agent without engineering intervention?
2. Is the agent persistent?
3. Can we prove exactly which model/version completed the work?
4. Can we prove what prompt/version was used?
5. Can we calculate the cost of one mission?
6. Can we reconstruct every material event?
7. Can a restricted agent bypass its tool policy?
8. Can the platform recover from interruption?
9. Does retry create duplicate output?
10. Can we replace the model provider later?
11. Can we replace the runtime later?
12. Is the architecture ready for the 3D world to consume events?
13. Is any Phase 1 work hiding inside Phase 0?
14. Is there enough evidence to justify continued investment?

---

# 36. Phase 0 End State

When Phase 0 is complete, Daythree AI World will not yet look like a world.

That is intentional.

It will instead have something more important:

- a real digital employee identity,
- a durable mission engine,
- a governed execution runtime,
- model abstraction,
- permission controls,
- budget controls,
- traceable artifacts,
- an event backbone,
- recovery capability,
- observability,
- auditability,
- and a testable foundation.

Only after this foundation is proven should the project proceed to **Phase 1 — Agent Creation Studio**, followed by **Phase 2 — Multi-Agent Team Formation**, and then **Phase 3 — the visible 3D Digital Twin**.

The foundation must be trustworthy before the world becomes beautiful.
