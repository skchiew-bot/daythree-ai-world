# ADR-014: Projects and the Town Layout

Status: **Accepted for planning** (2026-09-19). Gate review and data-warden conditions folded in.
No implementation has started. Executable phases `P1` (backend) and `W2` (frontend) are in
`docs/architecture/DIGITAL_TWIN_PROGRAM_BUILD_PLAN.md`. Builds on ADR-009 (rooms) and W1
(ADR-013 decision 6).

## Context

Operator intent (Chiew Sin Kwang, 2026-09-19, after the first look at W1 with real data):
"very cluttered, make more buildings, roads, ai can drive or ride a bicycle, motorbike.... each
project is a new building, common task are done at a community hall (shared services) and add more
creativity and make the world broader similarly like a small town which later can be a city."

Facts in current code that decide the shape (each verified by the chair at the cited lines):

- The platform has no "project". `Mission` (`packages/common/db/models.py`) has `mission_code`
  (globally unique, machine-generated), title, objective, status, `assigned_agent_id`, and no
  grouping above it.
- Every migration so far uses `Base.metadata.create_all(checkfirst=True)`
  (`infrastructure/migrations/versions/0003_agent_room_assignments.py` line 30). `checkfirst`
  tests table existence, so this pattern can never add a column to an existing table. Every test
  builds its schema from the models (`tests/conftest.py` line 53,
  `tests/integration/test_agent_rooms_concurrency.py` line 32); CI runs `alembic upgrade head`
  only against a database it just created (`.github/workflows/ci.yml` lines 168 and 195). A
  column added to `missions` through this pattern would pass every test and be absent from the
  live database.
- The world read (`services/api/routes/agent_rooms.py` lines 53 to 67) tenant-filters its
  subquery but the outer `select(Task)` carries no tenant predicate; it is contained today only
  because agent ids are tenant-unique and the selected columns are task-local.
- `Task.created_at` is `server_default=func.now()` (`models.py` line 203), which is constant within
  a transaction, and `_latest_task_by_agent` picks among equal timestamps with no `ORDER BY`.
- W1's render payload is a branded allow-list of five fields (`apps/admin-web/src/world/
  renderPayload.ts`), enforced by a type test in CI. `World.tsx` still renders `focusMission.title`
  (line 84) and `job_description` (line 150) in HTML cards beside the canvas.
- `GET /agent-rooms` writes on read (lazy `ensure_assignment`, lines 88 to 94) and has no rate
  limit. The admin UI polls it every 3 s.
- Migrations on disk: `0001` to `0003`; `0003b_model_invocations_index` is in PR #24; `0004` to
  `0008` are reserved by ADR-010 to ADR-013 in planning documents only, with no files.

## Decision

Two phases: `P1` gives the platform projects and a world read that can place twins; `W2` builds the
town. `W2` depends on `P1`. Neither touches room allocation.

1. **Projects are a first-class entity; missions link to them through a side table.**
   `projects(id, tenant_id, code, name, status active|archived, created_at)` with
   `UNIQUE(tenant_id, code)` and `UNIQUE(tenant_id, id)`; `mission_projects(mission_id PK,
   tenant_id, project_id, created_at)` with a composite FK `(tenant_id, project_id)` to
   `projects(tenant_id, id)`, so a mission can never link to another tenant's project at the
   database level. No existing table gains a column; the four-ADR invariant holds and the
   `create_all` migration pattern stays honest. Migration `0003c_projects`, `down_revision` = the
   real head at merge (`0003b` if PR #24 lands first, else `0003`), recorded in the migration
   docstring; `downgrade()` drops the two tables and is exercised in CI.
2. **Routes.** `POST /api/v1/projects` and `POST .../{id}/archive` behind a router-local role
   constant (`platform_admin`, `tenant_admin`, `operator`, the `model_policies.py` precedent) with
   the same fixed-window rate limit as `model_policies.py`; `GET /api/v1/projects` for any
   authenticated user. `code`: 1 to 20 characters, `^[A-Z0-9][A-Z0-9_-]*$`, 409 scoped to the
   tenant; `name`: 1 to 80 printable characters, no control characters. A per-tenant cap of 48
   active projects (the grid has 48 lots). Mission create and update accept an optional
   `project_id`, resolved with `get_tenant_scoped_or_404`. `audit_events.payload` for create and
   archive carries `project_id`, `status` and the actor id only.
3. **One polled endpoint.** `GET /api/v1/agent-rooms` is extended, not duplicated: each agent
   gains `project_id` (nullable), and the response gains `projects: [{id, code, name, status}]`
   containing every active project plus every project referenced by an emitted `project_id`, even
   when archived. The outer query filters `Mission.tenant_id` and `Project.tenant_id` explicitly;
   one deterministic task per agent (`DISTINCT ON (assigned_agent_id) ... ORDER BY
   assigned_agent_id, created_at DESC, id DESC`); placement and `activity` come from the same row.
   `project_id` is non-null only while `activity` is `assigned` or `working` or inside the result
   hold window; otherwise it is null and the twin is at the residence. Projects are loaded in one
   query over the referenced id set. The lazy room backfill stays where it is, in this one route.
4. **The town (W2, frontend only).** The ADR-009 apartment becomes the residence and keeps its
   rooms unchanged. Each project is a building on a deterministic street grid: buildings are
   placed by probing from `hash(project.id)` in the API's `(created_at, id)` order and taking the
   first free lot, so adding a project never moves another and two projects never share a lot.
   A community hall is where missions with no project are worked. Roads connect residence, hall
   and every lot. Twins commute: a walk for short hops, a bicycle or motorbike for longer streets,
   chosen only from trip distance and `agent_id`. A twin whose task ends walks home along the
   roads rather than snapping (room reassignment still snaps, ADR-009). Camera: town overview plus
   click to focus a building. `prefers-reduced-motion` keeps everyone in place.
5. **What the scene may show.** The allow-list grows by exactly `project_id` on `WorldAgent` and a
   separate branded `WorldProject = {id, code}` built field by field; `name` is never rendered in
   the canvas (it stays in the HTML sidebar). Vehicle type, building height and building size
   derive only from non-monetary, non-client state (distance, agent id, lot); never from budget,
   spend, deal size or task count. The scene label stays counts-only. Before W2 adds building
   signage, `World.tsx`'s existing `focusMission.title` and `job_description` cards go through the
   same allow-list discipline (data-warden D18).
6. **Not in this ADR.** Vehicles tied to credits or materials (ADR-011 L2, after L1 exists); a
   delivery car for accepted artifacts (`0006_artifact_reviews`, unbuilt); the pooled "Bench" twin
   (ADR-011 O1, still open; the hall is defined as "where missions with no project are worked"
   and nothing more); any change to `room_assignment.py` or `packages/common/rooms.py`; any new
   role or edit to a `MUTATORS` set.

## Gate Review Outcome (guardian-gatekeeper, 2026-09-19)

Verdict on the brief: **BLOCK + ALTERNATIVE** on `missions.project_id` through the `create_all`
pattern and on a migration numbered `0009`; **PASS WITH CONDITIONS C1 to C9** on projects, the town
and the world read. The decision above is the alternative. Findings, verified by the chair where
marked:

- **F1 CRITICAL (verified), the column no migration adds.** `create_all(checkfirst=True)` skips
  existing tables; tests build from models; CI upgrades an empty DB. A live DB would 500 on
  `GET /missions` while the migration log says success. *Adopted:* side table (decision 1).
- **F2 HIGH, `0009` has no parent on disk.** Alembic resolves `down_revision` against files.
  *Adopted:* `0003c_projects` against the real head (decision 1).
- **F3 CRITICAL (verified), no tenant predicate on the outer world query.** A project join would
  ride on an unfiltered Mission. *Adopted:* explicit filters plus a two-tenant security test with
  identical `created_at` (decision 3).
- **F4 HIGH, nothing at the DB forces mission and project into one tenant.** *Adopted:* composite
  FK on `(tenant_id, project_id)` (decision 1).
- **F5 HIGH (verified), non-deterministic active-task pick.** Equal `created_at` within a
  transaction and no `ORDER BY`; under projects the twin would teleport between buildings on
  successive polls. *Adopted:* `DISTINCT ON` with a tie-break (decision 3).
- **F6 HIGH, placement had no end and archiving stranded the avatar.** *Adopted:* `project_id`
  lifetime contract, archived-but-referenced projects still returned, walk home (decisions 3, 4).
- **F7 MEDIUM, 32-bit hash lot collisions.** About 96% chance of a shared lot at 20 projects over
  64 lots. *Adopted:* probe from the hash in a stable order (decision 4), with a test that adding
  a project moves no existing lot.
- **F8 MEDIUM, placement must key on ids.** *Adopted:* `project.id` only; `code` is signage
  (decisions 4, 5).
- **F9 MEDIUM, a second polled endpoint doubles a GET that writes.** *Adopted:* extend
  `/agent-rooms` (decision 3).
- **F10 MEDIUM, unbounded projects and payload.** *Adopted:* rate limit, per-tenant cap, one
  query, response scoped (decisions 2, 3).
- **F11 LOW, project codes must be tenant-unique, never global.** *Adopted:* decision 2.

Conditions C1 to C9 map onto the decisions and are restated as exit criteria in the build plan.

## Data-warden review (guardian-data-warden, 2026-09-19)

Verdict: **PASS WITH CONDITIONS D12 to D18**, continuing the list. The operator's real projects are
client engagements, so project names may be client names, and the canvas is the surface most
likely to be screenshotted and shared.

- **D12.** Length and character caps on `code` and `name`, enforced at the API (decision 2).
- **D13.** The scene renders `code` only, never `name` (decision 5).
- **D14.** The create-project form shows a persistent warning: the code may appear in shared
  screenshots; use an internal codename, not a client's legal name.
- **D15.** Vehicle type and building size derive only from non-monetary, non-client state
  (decision 5), stated in the ADR itself.
- **D16.** Council inputs (ADR-011 D2) receive `project_id` and `status` only.
- **D17.** `audit_events.payload` for project events carries ids, status and actor only.
- **D18.** `World.tsx` lines 84 and 150 (`focusMission.title`, `job_description`) go through the
  allow-list discipline before the canvas gains signage (decision 5).

## Consequences

- One additive migration (`0003c`): two new tables, no new columns on existing tables. Rollback
  drops both; missions keep working without projects.
- Two pre-existing defects in the world read are fixed on the way (F3 tenant predicate, F5
  determinism) and get their own regression tests.
- The operator gains two controls: create or archive a project, and attach a mission to one.
  Twins gain nothing they can trigger.
- The residence is unchanged; every ADR-009 guarantee about rooms holds.

## Operator decisions (Chiew Sin Kwang, 2026-09-19)

- **O15. Decided:** 48 lots on 6 streets of 8; the residence and the community hall anchor the
  main street. The per-tenant cap of 48 active projects matches the lot count.
- **O16. Decided:** yes, the community hall hosts the Bench twin once that twin exists. The Bench
  twin itself remains ADR-011 O1's open item and is not built in W2.
- **O17. Decided:** the World page sidebar may show a project's `code` and `name`; the canvas shows
  `code` only (D13 unchanged).

## Rollback Path

Revert the W2 PR (frontend only, the W1 world returns). Revert the P1 PRs and run `0003c`'s
`downgrade()`; `GET /agent-rooms` returns to its W1 shape because the projects fields are additive
and nullable.
