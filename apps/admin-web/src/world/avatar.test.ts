import * as THREE from "three";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { Pose } from "./agentMotion";
import type { AgentState } from "./agentState";
import { buildAvatar, createAnimState, createAvatarAssets, updateAvatar, type AvatarAssets, type AvatarHandle } from "./avatar";

const STILL: Pose = { x: 0, z: 0, heading: 0, speed: 0, walking: false, atDesk: false, phase: "room" };

describe("result ring visibility", () => {
  let scene: THREE.Scene;
  let assets: AvatarAssets;
  let avatar: AvatarHandle;
  const anim = createAnimState("agent-1");

  beforeEach(() => {
    scene = new THREE.Scene();
    assets = createAvatarAssets();
    avatar = buildAvatar(scene, assets, "agent-1", 0);
  });

  afterEach(() => {
    avatar.dispose();
    assets.dispose();
  });

  function step(state: AgentState) {
    updateAvatar(avatar, anim, state, STILL, 1, 1 / 60, false);
  }

  it("is not drawn before any result", () => {
    expect(avatar.resultRing.visible).toBe(false);
  });

  it("stays hidden for idle, assigned and working states", () => {
    for (const state of ["idle", "assigned", "working", "thinking"] as AgentState[]) {
      step(state);
      expect(avatar.resultRing.visible).toBe(false);
    }
  });

  it("shows for completed and failed, then hides again", () => {
    step("completed");
    expect(avatar.resultRing.visible).toBe(true);
    step("failed");
    expect(avatar.resultRing.visible).toBe(true);
    step("idle");
    expect(avatar.resultRing.visible).toBe(false);
  });
});
