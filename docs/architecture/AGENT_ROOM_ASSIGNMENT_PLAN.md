# Implementation Plan: Agent Room Assignment (ADR-009)

Status: PLANNED, not yet approved for implementation. Decision record: `docs/adr/ADR-009-agent-room-assignment.md`.

## Overview

Give every governed agent (`agents` row) a persistent, tenant-scoped room in a 5-floor x 4-room apartment, persisted in a new additive table `agent_room_assignments`. Rooms replace the single shared desk in the 3D world: each room gets its own desk position and its own idle position, and the avatar walks between them driven by real task-assignment state. Assignment never gates registration, is idempotent per `agents.id`, and is released on suspend.

## Resolved scope carried in from the ADR

Per-tenant apartment; soft cap with elastic floors; assignment strictly after registration; new additive table with a partial unique index as the concurrency guarantee; `create_all(checkfirst=True)` migration pattern; external agents out of scope; suspend releases; `external_agents.py` hardening untouched.

## Operator refinement folded in

Per-room desk. Task assignment triggers the walk from the room's idle spot to the room's desk.

## Key facts established by reading the current code

- `services/api/dependencies/db.py` commits on clean return and rolls back on any exception. Anything that raises inside `create_agent` destroys the agent registration. The allocator must be exception-contained.
- Agents are created in three places, only one of which is the API route: `services/api/routes/agents.py:42`, `infrastructure/scripts/seed.py:95` and `:152`, and test fixtures. A hook in the route alone leaves seeded agents roomless, so the plan uses lazy backfill on the read path too.
- `Task` has no `tenant_id`; tenant scoping goes through `Mission`. Room-activity queries must join missions.
- No tenant-wide task listing endpoint exists today.
- `World.tsx` derives every position from array order (`ATLAS_IDLE_POSITION`, `ATLAS_DESK_POSITION`, `EXTERNAL_ROW_Z`, `slotPosition(index, total)`).
- `apps/admin-web` has no test runner; CI runs `typecheck` and `build` only.
- `checkfirst=True` in `create_all` checks table existence, not index existence (risk R1).

## Where "task assigned to this agent" is signalled today

1. `tasks.assigned_agent_id` + `tasks.status` (`queued | running | waiting | failed | completed | cancelled`). Authoritative.
2. `missions.assigned_agent_id` + `missions.status` (coarser; what `World.tsx` uses today).
3. `audit_events` with `agent_id` and `event_type in (task.created, task.assigned, task.started, task.completed, task.failed)`.

Decision: key the walk off (1), served server-side inside the rooms response.

| Latest non-terminal task | Room activity | Avatar target |
|---|---|---|
| `queued` | `assigned` | walks to its room's desk |
| `running` / `waiting` | `working` | at desk, active bob/spin |
| `completed` within `RESULT_HOLD_MS` | `completed` | at desk, green ring, then returns to idle |
| `failed`/`cancelled` within hold | `failed` | at desk, red ring, then returns to idle |
| none / terminal past hold | `idle` | walks back to its room's idle spot |

`thinking` stays timeline-derived and limited to the focus mission's agent, as today.

## Architecture Changes

New:
- `packages/common/rooms.py` (pure slot math and layout constants)
- `services/api/services/__init__.py`, `services/api/services/room_assignment.py`
- `services/api/schemas/agent_rooms.py`, `services/api/routes/agent_rooms.py`
- `infrastructure/migrations/versions/0003_agent_room_assignments.py`
- `apps/admin-web/src/world/layout.ts`, `apartment.ts`, `avatar.ts`, `agentState.ts`

Modified:
- `packages/common/db/models.py` (add `AgentRoomAssignment`)
- `services/api/routes/agents.py` (post-registration hook, release-on-suspend, reassign-on-activate)
- `services/api/routes/__init__.py`
- `apps/admin-web/src/types/api.ts`, `apps/admin-web/src/api/hooks.ts`
- `apps/admin-web/src/pages/World.tsx` (reworked and shrunk)

Not modified: `services/api/routes/external_agents.py`, `Agent` / `ExternalAgentStatus` models (no ALTER), `infrastructure/scripts/seed.py`.

## Implementation Steps

### Phase 1: Schema and migration

1. Add `AgentRoomAssignment` to `models.py`: `id`, `tenant_id` FK, `agent_id` FK, `floor`, `room_index`, `assigned_at` (server default now), `released_at` nullable. Constraints: `ck_agent_room_assignments_room_index` (1..4), `ck_agent_room_assignments_floor` (>= 1), partial unique index `uq_agent_room_assignments_active_room` on `(tenant_id, floor, room_index) WHERE released_at IS NULL`, and (open decision D1) partial unique index `uq_agent_room_assignments_active_agent` on `(tenant_id, agent_id) WHERE released_at IS NULL`.
2. Add `packages/common/rooms.py`: `ROOMS_PER_FLOOR = 4`, `DEFAULT_FLOOR_COUNT = 5`, `slot_to_room(slot) -> (slot // 4 + 1, slot % 4 + 1)`, `room_to_slot`, `lowest_free_slot(occupied)`.
3. Migration `0003_agent_room_assignments.py`, `down_revision = "0002_external_agent_statuses"`. `upgrade()`: `create_all(checkfirst=True)` then an explicit sweep `for index in AgentRoomAssignment.__table__.indexes: index.create(bind, checkfirst=True)` because `create_all` skips indexes when it skips an existing table. `downgrade()`: drop only this table.
4. Unit tests for slot math in `packages/common/tests/test_rooms.py`.

### Phase 2: Allocation service

5. `services/api/services/room_assignment.py` with `get_assignment`, `ensure_assignment`, `release_assignment`, `list_assignments`. `ensure_assignment`: check-first, scan occupied slots, insert inside `session.begin_nested()`, on `IntegrityError` re-check then retry (max 5), return `None` on exhaustion. Determinism comes from the persisted row, never from hashing `agent_id`. Never raises into a registering caller.
6. Wire into `routes/agents.py`: `ensure_assignment` after `session.refresh(agent)` in `create_agent` wrapped in `try/except Exception` + log; `release_assignment` in `suspend_agent`; `ensure_assignment` in `activate_agent` (D2).

### Phase 3: Read API

7. Schemas `AgentRoomOut` (`agent_id`, `agent_code`, `display_name`, `lifecycle_state`, `floor`, `room_index`, `assigned_at`, `activity`, `active_task_id`, `activity_changed_at`) and `AgentRoomsResponse` (`rooms_per_floor`, `default_floor_count`, `rooms`). The envelope carries the layout contract so the frontend never hardcodes it.
8. `GET /api/v1/agent-rooms` (any authenticated role): load non-suspended agents, load active assignments, lazy-backfill missing ones via `ensure_assignment`, compute activity in one joined `Task JOIN Mission` query. A GET that writes is acknowledged in the docstring and is safe because the write is idempotent and DB-guarded.
9. Register router in `routes/__init__.py`.

### Phase 4: World.tsx rework and the per-room desk

10. `apps/admin-web/src/world/layout.ts`: `ROOM_WIDTH = 2.4`, `ROOM_DEPTH = 2.2`, `FLOOR_HEIGHT = 1.9`; `roomAnchors(floor, roomIndex) -> { center, idle, desk, deskProp }`. Depends only on `(floor, roomIndex)`, never on array index.
11. `avatar.ts`: move `AgentState`, `STATE_COLOR`, `AvatarHandle`, `buildAvatar`, `updateAvatar` out of `World.tsx`; fold `assigned` into the walk trigger so the walk starts on hand-over, not on worker pickup.
12. `apartment.ts`: `buildApartment(scene, { floors, roomsPerFloor })` builds floor slabs, dividers, per-room desk prop and a room status panel whose emissive tints to `STATE_COLOR[state]` so state reads at building scale. `floors = max(default_floor_count, max(assignment.floor))`. Widen camera target, `maxDistance`, fog, ground plane.
13. `agentState.ts`: move `pickFocusMission`, `deriveMissionAgentState`, `deriveExternalAgentState`, `RESULT_HOLD_MS`; add `deriveRoomAgentState(room, focusAgentId, timelineEventTypes, now)`.
14. Rework `World.tsx`: delete `ATLAS_*` constants, the inline desk, `atlas` handle; add `roomStatesRef`/`roomsRef`; sync avatars by `agent_id`; snap (do not lerp) on room change (D5); sync key `rooms.map(r => `${r.agent_id}:${r.floor}:${r.room_index}`).join("|")`. External agents stay exactly as they are on the ground row. Replace the "desk avatar" page copy with a per-floor room occupancy table.
15. `types/api.ts` + `api/hooks.ts`: `useAgentRooms()` with `refetchInterval: 3_000`; invalidate `["agent-rooms"]` from create/suspend/activate mutations.

## Test Plan

Unit (`packages/common/tests/test_rooms.py`): first occupant -> (1,1); fourth -> (1,4); fifth -> (2,1); twentieth -> (5,4); twenty-first -> (6,1) (soft-cap property); round trip 0..40; lowest free slot fills a released gap; empty tenant -> 0.

Integration (`tests/integration/test_agent_rooms.py`): registering assigns a room; idempotent across a fresh session (restart); 21st agent returns 201 and lands on floor 6 room 1; suspend releases; released room reused; registration survives an allocator exception (the key regression test for the `db.py` rollback hazard); seeded agent roomed on first read; activity reflects `queued` -> `assigned`, `running` -> `working`.

Concurrency (own `async_sessionmaker` over two connections): partial unique index rejects double occupancy; permits reuse after release (proves the `WHERE` predicate exists); 8 concurrent distinct agents -> 8 distinct rooms; 2 concurrent ensures for one agent -> 1 active row.

Cross-tenant (`tests/security/test_agent_rooms_isolation.py`): both tenants occupy (1,1); tenant never sees another's rooms; endpoint requires auth.

Migration (`tests/integration/test_migrations.py`): upgrade head on fresh DB creates table and both partial indexes (assert on `pg_indexes.indexdef` containing `WHERE (released_at IS NULL)`); upgrade from `0002` gives identical result; downgrade drops only the new table.

Frontend: preferred option adds `vitest` (D3) with `src/world/__tests__/layout.test.ts` pinning anchor determinism; fallback is typecheck plus a Playwright assertion on the room table.

## Risks

- R1 (High): `checkfirst=True` silently skips indexes when the table exists. Mitigated by the index sweep and `indexdef` assertions.
- R2 (High): an exception in the room hook destroys agent registration. Mitigated by savepoint + try/except + regression test.
- R3 (Medium): check-then-act idempotency under 3s polling from multiple tabs. Mitigated by the agent-side partial unique index (D1).
- R4 (Medium): plain unique constraint substituted for the partial index. Mitigated by the reuse-after-release test.
- R5 (Medium): N+1 timeline polling. Mitigated by server-side activity in the rooms envelope.
- R6 (Low): `World.tsx` file size. Mitigated by extractions before adding the building.
- R7 (Low): floor 6+ shell missing. Mitigated by deriving floor count from max assignment floor.

## Open Decisions

- D1: add the `(tenant_id, agent_id)` partial unique index (recommended).
- D2: does `activate` reassign a room? Recommended yes; a reactivated agent may land in a different room if its old one was taken.
- D3: add `vitest` to `apps/admin-web` (recommended).
- D4: exact desk/idle offsets inside a room (visual tuning, live in `layout.ts`).
- D5: snap vs lerp on room change (recommended snap).
- D6: test naming without spec TC-P0 IDs (recommended descriptive names citing ADR-009).
- D7: no audit events for room assignment (recommended; if overruled, emit only from `create_agent`/`suspend_agent`, never from the read path).
- D8: embed activity in the rooms response vs a separate tenant-wide task endpoint (recommended embed).

## Success Criteria

- `alembic upgrade head` creates the table with both partial unique indexes on a fresh DB and on a DB at `0002`; downgrade drops only the new table.
- `POST /api/v1/agents` returns 201 and assigns a room; still 201 when the allocator raises.
- Occupant 21 lands on floor 6 room 1.
- Two tenants independently occupy (1,1) and never see each other's rooms.
- Concurrent allocation never double-books; concurrent ensure for one agent yields one room.
- An agent returns to the same room after a restart; suspend releases; freed room is reused.
- Seeded agents are roomed on first read without touching `seed.py`.
- `World.tsx` derives no governed-agent position from array index; registering an unrelated agent moves nobody.
- Each roomed agent walks to its own room's desk on task assignment and back to idle when done; the room panel makes state readable at building scale.
- `npm run typecheck`, `npm run build`, and the Playwright journey pass; `external_agents.py` is unmodified.
