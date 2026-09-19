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
  /** Owned by this entry and rewritten every frame, so a frame allocates no context. The
   * motion functions read it and never keep a reference. */
  ctx: MotionContext;
  floor: number;
  roomIndex: number;
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
      this.reconcile(agents, apartment);
      this.lastAgents = agents;
    }
    for (const agent of agents) {
      const state = states.get(agent.agent_id) ?? agent.activity;
      const entry = this.entryFor(agent, state, clock);
      refreshContext(entry.ctx, agent, state, clock);
      entry.motion = stepMotion(entry.motion, entry.ctx, clock.dt);
      entry.floor = agent.floor;
      entry.roomIndex = agent.room_index;
      entry.handle.floorY = floorY(agent.floor);
      updateAvatar(entry.handle, entry.anim, state, poseOf(entry.motion), clock.t, clock.dt, clock.reducedMotion);
      tintRoomPanel(apartment, agent.floor, agent.room_index, state);
    }
  }

  dispose(): void {
    this.entries.forEach((entry) => entry.handle.dispose());
    this.entries.clear();
  }

  private entryFor(agent: WorldAgent, state: AgentState, clock: FrameClock): Entry {
    const existing = this.entries.get(agent.agent_id);
    if (existing) return existing;

    const ctx: MotionContext = {
      agentId: agent.agent_id,
      floor: agent.floor,
      roomIndex: agent.room_index,
      state,
      nowMs: clock.nowMs,
      reducedMotion: clock.reducedMotion,
    };
    const entry: Entry = {
      handle: buildAvatar(this.scene, this.assets, agent.agent_id, floorY(agent.floor)),
      anim: createAnimState(agent.agent_id),
      motion: initMotion(ctx),
      ctx,
      floor: agent.floor,
      roomIndex: agent.room_index,
    };
    this.entries.set(agent.agent_id, entry);
    return entry;
  }

  /** Runs when new data arrives. A room an agent has left (removed or reassigned) has its
   * status panel put back to the idle tint; occupants re-tint their rooms afterwards in
   * the same update, so a swap of two rooms still ends up right. */
  private reconcile(agents: readonly WorldAgent[], apartment: ApartmentHandle): void {
    const present = new Map(agents.map((a) => [a.agent_id, a]));
    for (const [id, entry] of this.entries) {
      const agent = present.get(id);
      if (agent && agent.floor === entry.floor && agent.room_index === entry.roomIndex) continue;
      tintRoomPanel(apartment, entry.floor, entry.roomIndex, "idle");
      if (agent) continue;
      entry.handle.dispose();
      this.entries.delete(id);
    }
  }
}

function refreshContext(ctx: MotionContext, agent: WorldAgent, state: AgentState, clock: FrameClock): void {
  ctx.floor = agent.floor;
  ctx.roomIndex = agent.room_index;
  ctx.state = state;
  ctx.nowMs = clock.nowMs;
  ctx.reducedMotion = clock.reducedMotion;
}
