import * as THREE from "three";
import { describe, expect, it } from "vitest";

import type { AgentRoom } from "@/types/api";

import type { AgentState } from "./agentState";
import type { ApartmentHandle } from "./apartment";
import { createAvatarAssets } from "./avatar";
import { assignLots } from "./lots";
import { toWorldAgent, type WorldAgent } from "./renderPayload";
import type { FrameClock } from "./roomAvatars";
import { buildTownPlan, RESIDENCE_ENTRANCE } from "./town";
import { TownAvatars } from "./townAvatars";
import { createVehicleAssets } from "./vehicles";

const plan = buildTownPlan();
const lotOf = assignLots(["p-1"]);

function agent(activity: AgentRoom["activity"], projectId: string | null): WorldAgent {
  return toWorldAgent({
    agent_id: "a-1",
    agent_code: "AG-1",
    display_name: "Twin",
    lifecycle_state: "active",
    floor: 1,
    room_index: 1,
    assigned_at: "2026-09-19T08:00:00Z",
    activity,
    active_task_id: null,
    activity_changed_at: null,
    project_id: projectId,
  });
}

function setup() {
  const scene = new THREE.Scene();
  const avatars = new TownAvatars(scene, createAvatarAssets(), createVehicleAssets(), plan);
  const apartment = { panels: new Map(), floors: 1, group: new THREE.Group(), dispose: () => {} } as unknown as ApartmentHandle;
  const states = new Map<string, AgentState>();
  return { scene, avatars, apartment, states };
}

function clock(nowMs: number, reducedMotion = false): FrameClock {
  return { t: nowMs / 1000, dt: 0.1, nowMs, reducedMotion };
}

/** The avatar group of the first away twin: buildAvatar adds it before any vehicle. */
function awayGroup(scene: THREE.Scene, before: ReadonlySet<THREE.Object3D>): THREE.Object3D | undefined {
  return scene.children.find((c) => c.type === "Group" && !before.has(c));
}

describe("TownAvatars commuting (ADR-014 W2)", () => {
  it("sends a twin out along the road when it gets a project, then walks it home when the task ends", () => {
    const { scene, avatars, apartment, states } = setup();
    const idle = [agent("idle", null)];

    avatars.update(idle, states, apartment, lotOf, clock(0));
    const homeChildren = new Set(scene.children);

    const working = [agent("working", "p-1")];
    avatars.update(working, states, apartment, lotOf, clock(1_000));
    const away = awayGroup(scene, homeChildren);
    expect(away).toBeDefined();

    // Sample the trip: the twin leaves the residence entrance and keeps moving.
    const trail: number[] = [];
    for (let ms = 1_000; ms <= 30_000; ms += 500) {
      avatars.update(working, states, apartment, lotOf, clock(ms));
      trail.push(Math.hypot(away!.position.x - RESIDENCE_ENTRANCE.x, away!.position.z - RESIDENCE_ENTRANCE.z));
    }
    expect(Math.max(...trail)).toBeGreaterThan(20);

    // Task ends: project_id null and idle. It is still away and walks back, not snapped.
    const finished = [agent("idle", null)];
    avatars.update(finished, states, apartment, lotOf, clock(31_000));
    expect(away!.parent).toBe(scene);
    const leftAt = away!.position.clone();
    avatars.update(finished, states, apartment, lotOf, clock(33_000));
    // Two seconds into the walk home it has moved along the road but is nowhere near the
    // residence yet: no snap. (Its first leg may head away from the residence in a straight
    // line, since the road detours via a street end, so only "moved" is asserted here.)
    expect(away!.position.distanceTo(leftAt)).toBeGreaterThan(1);
    expect(away!.position.distanceTo(new THREE.Vector3(RESIDENCE_ENTRANCE.x, away!.position.y, RESIDENCE_ENTRANCE.z))).toBeGreaterThan(5);

    // Long after, it has arrived and been handed back to the residence.
    for (let ms = 33_000; ms <= 120_000; ms += 500) avatars.update(finished, states, apartment, lotOf, clock(ms));
    expect(away!.parent).toBeNull();
  });

  it("uses a vehicle for a long trip and frees it on arrival", () => {
    const { scene, avatars, apartment, states } = setup();
    const start = new Set(scene.children);
    const working = [agent("working", "p-1")];

    avatars.update([agent("idle", null)], states, apartment, lotOf, clock(0));
    avatars.update(working, states, apartment, lotOf, clock(1_000));
    const groups = scene.children.filter((c) => c.type === "Group" && !start.has(c));
    // avatar + vehicle: the residence-to-lot trip is well past walking distance
    expect(groups.length).toBeGreaterThanOrEqual(2);

    for (let ms = 1_000; ms <= 60_000; ms += 500) avatars.update(working, states, apartment, lotOf, clock(ms));
    const after = scene.children.filter((c) => c.type === "Group" && !start.has(c));
    expect(after.length).toBe(1);
  });

  it("does not commute under reduced motion: the twin appears at its building at once", () => {
    const { scene, avatars, apartment, states } = setup();
    avatars.update([agent("idle", null)], states, apartment, lotOf, clock(0, true));
    const homeChildren = new Set(scene.children);

    const working = [agent("working", "p-1")];
    avatars.update(working, states, apartment, lotOf, clock(1_000, true));
    const away = awayGroup(scene, homeChildren);
    const lot = plan.lots[lotOf.get("p-1")!];
    expect(Math.abs(away!.position.z - plan.roads.nodes.get(lot.roadNode)!.z)).toBeLessThan(0.01);
    const first = away!.position.clone();
    avatars.update(working, states, apartment, lotOf, clock(5_000, true));
    expect(away!.position.distanceTo(first)).toBeLessThan(1e-6);
  });

  it("keeps a just-finished result visible at the building: the away twin shows its result ring", () => {
    // Chosen behaviour (ADR-014 W2): a room whose occupant is out at a building reads idle;
    // a completed or failed result is shown on the twin itself, at its building, for the
    // server's hold window (the activity stays completed/failed and project_id stays set).
    const { scene, avatars, apartment, states } = setup();
    for (const activity of ["completed", "failed"] as const) {
      const before = new Set(scene.children);
      avatars.update([agent(activity, "p-1")], states, apartment, lotOf, clock(0, true));
      avatars.update([agent(activity, "p-1")], states, apartment, lotOf, clock(1_000, true));
      const rings = scene.children.filter((c) => c.type === "Mesh" && !before.has(c) && c.visible);
      expect(rings.length, activity).toBe(1);
      avatars.dispose();
    }
  });

  it("frees every away avatar on dispose", () => {
    const { scene, avatars, apartment, states } = setup();
    avatars.update([agent("working", "p-1")], states, apartment, lotOf, clock(0));
    avatars.dispose();
    expect(scene.children.filter((c) => c.type === "Group")).toHaveLength(0);
  });
});
