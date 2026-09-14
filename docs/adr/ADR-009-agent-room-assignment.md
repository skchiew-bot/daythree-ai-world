# ADR-009: Agent Room Assignment (20-Room Apartment)

## Context

Requirement from the operator (Chiew Sin Kwang, 2026-09-14): "All agents will be
assigned and stay in a 20-room apartment (4 rooms per floor)."

`guardian-gatekeeper` reviewed this before any implementation, per the standing gate
rule. Today there is no persistence layer for spatial placement at all — desk/avatar
position in the 3D world is derived entirely from array order in
`apps/admin-web/src/pages/World.tsx` (`ATLAS_DESK_POSITION`, `slotPosition(index,
total)`), and `packages/common/db/models.py` has no room, floor, or placement concept.

## Options Considered

1. **Hard 20-room pool gating registration** (the literal requirement): a fixed pool of
   20 rooms; agent assignment is required at registration time; no more than 20 agents
   can hold a room.
2. **Tenant-scoped, presentation-layer room assignment with elastic floors** (the
   gatekeeper's proposed alternative): rooms are assigned *after* registration succeeds,
   never gate it; floors compute elastically beyond 20; capacity is a soft/visual
   default, not an admission-control invariant.

## Decision

Option 2, with the following resolved scope (operator answers, 2026-09-14):

- **Per-tenant**: the apartment is scoped per tenant, not a single global building.
  Each tenant gets its own 20-room (5-floor × 4-room) view.
- **Soft cap**: 20 rooms is the visual/default layout, not a hard limit. Floors compute
  elastically (`floor = slot // 4 + 1`, `room_index = slot % 4 + 1`) so occupant 21+
  gets floor 6+ instead of a rejected registration.
- **Room replaces the desk**: the existing single-desk/walk-to-desk presentation in
  `World.tsx` (`ATLAS_DESK_POSITION`, `ATLAS_IDLE_POSITION`) is superseded by room
  assignment, not kept alongside it. The "agent is working" state signal needs a new
  expression once the desk goes away (open item for the implementation plan).
- **External-agent avatars are excluded from scope.** Only governed Daythree Agents
  (`agents` table rows) get room assignments. `external_agent_statuses` rows are not
  roomed. This also means the CRITICAL capacity-DoS failure path the gatekeeper
  identified (unauthenticated-role, unrate-limited `PUT
  /api/v1/external-agents/{name}/status` filling the room pool with fake names) does not
  apply as originally feared — external agents never compete for rooms. That endpoint's
  lack of a role check/rate limit is still a pre-existing gap, just no longer coupled to
  this feature; it is not fixed by this decision and remains open separately.
- **Suspend releases the room.** Suspending a governed agent frees its room assignment
  (`released_at` set); the room becomes available for reassignment. There is currently
  no delete route for agents (only `/suspend`), so release-on-suspend is the only
  deallocation path that exists today.
- **Floor number is purely spatial** — no department/autonomy-level/lifecycle-state
  meaning is encoded in floor assignment.

## Rationale

- The hard-pool option (1) makes agent onboarding capacity-gated with no deallocation
  path anywhere in the codebase at the time of review, and a single global pool
  inverts the tenant-isolation design already present everywhere else in the schema
  (`uq_agents_tenant_code`, `uq_external_agent_statuses_tenant_name`, 404-not-403 on
  cross-tenant lookups in `auth.py`). Both are governance-surface weakenings the
  gatekeeper is not permitted to wave through under the charter's non-negotiable #2.
- Making rooms presentation-only (never gating `POST /api/v1/agents`) removes the
  capacity-DoS failure path without giving up the "20 rooms, 4 per floor" visual the
  operator asked for — it is still exactly what renders for the first 20 occupants.
- Excluding external agents from scope removes the specific attacker-controllable path
  the gatekeeper flagged as CRITICAL (that endpoint has no role check and no rate
  limit), rather than requiring that endpoint be hardened as a prerequisite.

## Consequences

- New table required: `agent_room_assignments` (tenant-scoped, occupant is always a
  governed `agents.id` — no `occupant_kind` polymorphism needed now that external
  agents are excluded). Partial unique index on `(tenant_id, floor, room_index) WHERE
  released_at IS NULL` is the actual concurrency guarantee (prevents double occupancy),
  not application-level check-then-act — consistent with the idempotency approach in
  ADR-007.
- Migration must be additive only (new table, no `ALTER` on `agents` or
  `external_agent_statuses`), following the `create_all(checkfirst=True)` pattern used
  in `0001`/`0002`, and must be verified against both a fresh database and one already
  at the prior revision (the gatekeeper flagged an ordering hazard here if this isn't
  checked).
- `World.tsx` must stop deriving avatar position from array index and read from the
  assignment record instead, to stop desks/rooms teleporting when an unrelated agent
  registers.
- The desk-based "agent is working" visual signal needs a replacement now that rooms
  supersede the desk — to be resolved in the implementation plan, not this ADR.
- `external_agent_statuses.PUT` having no role check/rate limit remains a real gap;
  it is out of scope for this feature but should be tracked separately.

## Rollback Path

The new table is additive and isolated — `downgrade()` on its migration drops only
`agent_room_assignments`. No existing table or column is modified, so rollback never
touches agent registration, suspension, or external-agent status behavior.
