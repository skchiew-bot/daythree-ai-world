import * as THREE from "three";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { AgentRoom } from "@/types/api";

import type { AgentState } from "./agentState";
import type { ApartmentHandle } from "./apartment";
import { STATE_COLOR, createAvatarAssets, type AvatarAssets } from "./avatar";
import { roomKey } from "./layout";
import { toWorldAgent } from "./renderPayload";
import { RoomAvatars, type FrameClock } from "./roomAvatars";

const CLOCK: FrameClock = { t: 0, dt: 1 / 60, nowMs: Date.UTC(2026, 8, 19, 10), reducedMotion: false };

function worldAgent(id: string, floor: number, room: number, activity: AgentRoom["activity"] = "idle") {
  return toWorldAgent({
    agent_id: id,
    agent_code: id,
    display_name: id,
    lifecycle_state: "active",
    floor,
    room_index: room,
    assigned_at: "2026-09-19T08:00:00Z",
    activity,
    active_task_id: null,
    activity_changed_at: null,
    project_id: null,
  });
}

/** A building with just the status panels, which is all RoomAvatars touches. */
function fakeApartment(): ApartmentHandle {
  const panels: ApartmentHandle["panels"] = new Map();
  for (let floor = 1; floor <= 2; floor++) {
    for (let room = 1; room <= 4; room++) {
      const panelMaterial = new THREE.MeshStandardMaterial({ color: STATE_COLOR.idle, emissive: STATE_COLOR.idle });
      panels.set(roomKey(floor, room), { panelMaterial });
    }
  }
  return { group: new THREE.Group(), panels, floors: 2, dispose: () => undefined };
}

describe("RoomAvatars panel tint", () => {
  let scene: THREE.Scene;
  let assets: AvatarAssets;
  let avatars: RoomAvatars;
  let apartment: ApartmentHandle;

  const tint = (floor: number, room: number) => apartment.panels.get(roomKey(floor, room))!.panelMaterial.color.getHex();

  beforeEach(() => {
    scene = new THREE.Scene();
    assets = createAvatarAssets();
    avatars = new RoomAvatars(scene, assets);
    apartment = fakeApartment();
  });

  afterEach(() => {
    avatars.dispose();
    assets.dispose();
  });

  it("tints an occupied room with its agent's state", () => {
    const agents = [worldAgent("a", 1, 1, "working")];
    avatars.update(agents, new Map<string, AgentState>([["a", "working"]]), apartment, CLOCK);

    expect(tint(1, 1)).toBe(STATE_COLOR.working);
  });

  it("puts the panel back to idle when the agent is removed", () => {
    const states = new Map<string, AgentState>([["a", "failed"]]);
    avatars.update([worldAgent("a", 1, 2, "failed")], states, apartment, CLOCK);
    expect(tint(1, 2)).toBe(STATE_COLOR.failed);

    avatars.update([], new Map(), apartment, CLOCK);

    expect(tint(1, 2)).toBe(STATE_COLOR.idle);
    expect(scene.children).toHaveLength(0);
  });

  it("resets the old room and tints the new one when an agent is reassigned", () => {
    const states = new Map<string, AgentState>([["a", "working"]]);
    avatars.update([worldAgent("a", 1, 1, "working")], states, apartment, CLOCK);
    avatars.update([worldAgent("a", 2, 3, "working")], states, apartment, CLOCK);

    expect(tint(1, 1)).toBe(STATE_COLOR.idle);
    expect(tint(2, 3)).toBe(STATE_COLOR.working);
  });

  it("keeps both tints right when two agents swap rooms", () => {
    const states = new Map<string, AgentState>([["a", "working"], ["b", "failed"]]);
    avatars.update([worldAgent("a", 1, 1, "working"), worldAgent("b", 1, 2, "failed")], states, apartment, CLOCK);
    avatars.update([worldAgent("a", 1, 2, "working"), worldAgent("b", 1, 1, "failed")], states, apartment, CLOCK);

    expect(tint(1, 2)).toBe(STATE_COLOR.working);
    expect(tint(1, 1)).toBe(STATE_COLOR.failed);
  });
});
