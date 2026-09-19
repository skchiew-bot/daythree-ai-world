import * as THREE from "three";
import { describe, expect, it } from "vitest";

import type { AgentRoom } from "@/types/api";

import type { AgentState } from "./agentState";
import type { ApartmentHandle } from "./apartment";
import { createAvatarAssets } from "./avatar";
import { assignLots } from "./lots";
import { toWorldAgent, type WorldAgent } from "./renderPayload";
import type { FrameClock } from "./roomAvatars";
import { buildTownPlan } from "./town";
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
  return { avatars, apartment, states };
}

function clock(nowMs: number): FrameClock {
  return { t: nowMs / 1000, dt: 0.1, nowMs, reducedMotion: false };
}

/** ADR-014 W3 deliverable 5, W3-F3: `poseOf` is the only way the follow camera reads a
 * twin's position, and it must never read a handle that TownAvatars has already disposed. */
describe("TownAvatars.poseOf (ADR-014 W3, test 6)", () => {
  it("returns false for an agent that was never seen", () => {
    const { avatars } = setup();
    const out = { x: 0, z: 0, heading: 0 };
    expect(avatars.poseOf("nobody", out)).toBe(false);
  });

  it("returns true with a live position while the twin is away in town", () => {
    const { avatars, apartment, states } = setup();
    avatars.update([agent("working", "p-1")], states, apartment, lotOf, clock(0));
    const out = { x: 0, z: 0, heading: 0 };
    expect(avatars.poseOf("a-1", out)).toBe(true);
    expect(avatars.hasAway("a-1")).toBe(true);
    expect([...avatars.awayIds]).toEqual(["a-1"]);
  });

  it("returns false once the twin has walked home and been handed back to the residence", () => {
    const { avatars, apartment, states } = setup();
    avatars.update([agent("working", "p-1")], states, apartment, lotOf, clock(0));
    avatars.update([agent("idle", null)], states, apartment, lotOf, clock(1_000));
    for (let ms = 1_000; ms <= 120_000; ms += 500) {
      avatars.update([agent("idle", null)], states, apartment, lotOf, clock(ms));
    }
    const out = { x: 0, z: 0, heading: 0 };
    expect(avatars.poseOf("a-1", out)).toBe(false);
  });

  it("returns false once the agent leaves the payload entirely, with no error", () => {
    const { avatars, apartment, states } = setup();
    avatars.update([agent("working", "p-1")], states, apartment, lotOf, clock(0));
    avatars.update([], states, apartment, lotOf, clock(1_000));
    const out = { x: 0, z: 0, heading: 0 };
    expect(() => avatars.poseOf("a-1", out)).not.toThrow();
    expect(avatars.poseOf("a-1", out)).toBe(false);
  });
});
