import type * as THREE from "three";

import { initMotion, poseOf, stepMotion, type MotionContext, type MotionState } from "./agentMotion";
import type { AgentState } from "./agentState";
import { tintRoomPanel, type ApartmentHandle } from "./apartment";
import {
  buildAvatar,
  createAnimState,
  updateAvatar,
  type AvatarAnimState,
  type AvatarAssets,
  type AvatarHandle,
} from "./avatar";
import { floorY } from "./layout";
import type { WorldAgent } from "./renderPayload";

interface Entry {
  handle: AvatarHandle;
  anim: AvatarAnimState;
  motion: MotionState;
}

export interface FrameClock {
  t: number;
  dt: number;
  nowMs: number;
  reducedMotion: boolean;
}

/** One avatar per governed agent that holds a room, keyed by agent_id and never by array
 * index. Each frame it steps that agent's motion model from the allow-listed WorldAgent
 * and the derived state, and nothing else. */
export class RoomAvatars {
  private readonly entries = new Map<string, Entry>();
  private lastAgents: readonly WorldAgent[] = [];

  constructor(
    private readonly scene: THREE.Scene,
    private readonly assets: AvatarAssets,
  ) {}

  update(
    agents: readonly WorldAgent[],
    states: ReadonlyMap<string, AgentState>,
    apartment: ApartmentHandle,
    clock: FrameClock,
  ): void {
    if (agents !== this.lastAgents) {
      this.removeMissing(agents);
      this.lastAgents = agents;
    }
    for (const agent of agents) {
      const state = states.get(agent.agent_id) ?? agent.activity;
      const ctx = this.contextFor(agent, state, clock);
      const entry = this.entryFor(agent, ctx);
      entry.motion = stepMotion(entry.motion, ctx, clock.dt);
      entry.handle.floorY = floorY(agent.floor);
      updateAvatar(entry.handle, entry.anim, state, poseOf(entry.motion), clock.t, clock.dt, clock.reducedMotion);
      tintRoomPanel(apartment, agent.floor, agent.room_index, state);
    }
  }

  dispose(): void {
    this.entries.forEach((entry) => entry.handle.dispose());
    this.entries.clear();
  }

  private contextFor(agent: WorldAgent, state: AgentState, clock: FrameClock): MotionContext {
    return {
      agentId: agent.agent_id,
      floor: agent.floor,
      roomIndex: agent.room_index,
      state,
      nowMs: clock.nowMs,
      reducedMotion: clock.reducedMotion,
    };
  }

  private entryFor(agent: WorldAgent, ctx: MotionContext): Entry {
    const existing = this.entries.get(agent.agent_id);
    if (existing) return existing;
    const entry: Entry = {
      handle: buildAvatar(this.scene, this.assets, agent.agent_id, floorY(agent.floor)),
      anim: createAnimState(agent.agent_id),
      motion: initMotion(ctx),
    };
    this.entries.set(agent.agent_id, entry);
    return entry;
  }

  private removeMissing(agents: readonly WorldAgent[]): void {
    const present = new Set(agents.map((a) => a.agent_id));
    for (const [id, entry] of this.entries) {
      if (present.has(id)) continue;
      entry.handle.dispose();
      this.entries.delete(id);
    }
  }
}
