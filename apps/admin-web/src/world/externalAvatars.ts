import type * as THREE from "three";

import type { Pose } from "./agentMotion";
import type { AgentState } from "./agentState";
import { buildAvatar, createAnimState, updateAvatar, type AvatarAnimState, type AvatarAssets, type AvatarHandle } from "./avatar";
import type { FrameClock } from "./roomAvatars";

const EXTERNAL_ROW_Z = 4.4;
const SPACING = 1.6;

interface Entry {
  handle: AvatarHandle;
  anim: AvatarAnimState;
  x: number;
}

/** External agents (a Claude Code session, a script, anything pinging the status
 * endpoint) stand in a row in front of the building. They hold no room and never wander:
 * the row is unchanged from before ADR-009, only drawn with the new avatar. */
export class ExternalAvatars {
  private readonly entries = new Map<string, Entry>();
  private namesKey = "";

  constructor(
    private readonly scene: THREE.Scene,
    private readonly assets: AvatarAssets,
  ) {}

  update(names: readonly string[], states: ReadonlyMap<string, AgentState>, clock: FrameClock): void {
    const key = names.join("|");
    if (key !== this.namesKey) {
      this.sync(names);
      this.namesKey = key;
    }
    for (const [name, entry] of this.entries) {
      const state = states.get(name) ?? "idle";
      const pose: Pose = { x: entry.x, z: EXTERNAL_ROW_Z, heading: 0, speed: 0, walking: false, atDesk: false, phase: "room" };
      updateAvatar(entry.handle, entry.anim, state, pose, clock.t, clock.dt, clock.reducedMotion);
    }
  }

  dispose(): void {
    this.entries.forEach((entry) => entry.handle.dispose());
    this.entries.clear();
  }

  private sync(names: readonly string[]): void {
    for (const [name, entry] of this.entries) {
      if (names.includes(name)) continue;
      entry.handle.dispose();
      this.entries.delete(name);
    }
    const startX = -((names.length - 1) * SPACING) / 2;
    names.forEach((name, i) => {
      const x = startX + i * SPACING;
      const existing = this.entries.get(name);
      if (existing) {
        existing.x = x;
        return;
      }
      this.entries.set(name, { handle: buildAvatar(this.scene, this.assets, name, 0), anim: createAnimState(name), x });
    });
  }
}
