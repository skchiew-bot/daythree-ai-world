import type * as THREE from "three";

import type { Pose } from "./agentMotion";
import type { AgentState } from "./agentState";
import type { ApartmentHandle } from "./apartment";
import {
  buildAvatar,
  createAnimState,
  updateAvatar,
  type AvatarAnimState,
  type AvatarAssets,
  type AvatarHandle,
} from "./avatar";
import {
  initCommute,
  isArrivedAt,
  placeFor,
  poseAt,
  speedOf,
  stepCommute,
  type CommutePose,
  type CommuteState,
  type Place,
} from "./commute";
import type { WorldAgent } from "./renderPayload";
import { RoomAvatars, type FrameClock } from "./roomAvatars";
import type { TownPlan } from "./town";
import { buildVehicle, updateVehicle, type RideKind, type VehicleAssets, type VehicleHandle } from "./vehicles";

const RESIDENCE: Place = { kind: "residence" };
/** Fraction of the rider's rig height the hips sit above the avatar's origin (avatar.ts). */
const RIG_HIP_HEIGHT = 0.386;

interface AwayEntry {
  handle: AvatarHandle;
  anim: AvatarAnimState;
  vehicle: VehicleHandle | null;
  /** Owned by this entry and rewritten every frame, so a frame allocates no pose (the same
   * discipline as roomAvatars.ts). */
  commutePose: CommutePose;
  bodyPose: Pose;
}

/** Decides, per governed agent, whether it is at the residence (drawn by the unchanged W1
 * `RoomAvatars`, walking in its room and corridor) or out in town (drawn here, on the road
 * graph). Membership follows the commute state, not the raw activity: a twin whose task just
 * ended stays "away" until it has walked back to the residence, then hands over to
 * `RoomAvatars`, which places it in its room (ADR-009 snap semantics untouched). */
export class TownAvatars {
  private readonly rooms: RoomAvatars;
  private readonly commutes = new Map<string, CommuteState>();
  private readonly away = new Map<string, AwayEntry>();
  private lastAgents: readonly WorldAgent[] = [];
  private home: WorldAgent[] = [];
  private readonly scratch: WorldAgent[] = [];

  constructor(
    private readonly scene: THREE.Scene,
    private readonly avatarAssets: AvatarAssets,
    private readonly vehicleAssets: VehicleAssets,
    private readonly town: TownPlan,
  ) {
    this.rooms = new RoomAvatars(scene, avatarAssets);
  }

  update(
    agents: readonly WorldAgent[],
    states: ReadonlyMap<string, AgentState>,
    apartment: ApartmentHandle,
    lotOf: ReadonlyMap<string, number>,
    clock: FrameClock,
  ): void {
    const agentsChanged = agents !== this.lastAgents;
    if (agentsChanged) this.forgetMissing(agents);
    this.scratch.length = 0;

    for (const agent of agents) {
      const state = states.get(agent.agent_id) ?? agent.activity;
      const commute = this.advance(agent, lotOf, clock);
      if (isArrivedAt(commute, RESIDENCE)) {
        this.dropAway(agent.agent_id);
        this.scratch.push(agent);
      } else {
        this.updateAway(agent, state, commute, clock);
      }
    }

    if (agentsChanged || !sameAgents(this.scratch, this.home)) this.home = this.scratch.slice();
    this.lastAgents = agents;
    this.rooms.update(this.home, states, apartment, clock);
  }

  dispose(): void {
    this.rooms.dispose();
    this.away.forEach((entry) => this.release(entry));
    this.away.clear();
    this.commutes.clear();
  }

  /** Every agent currently out in town (not at the residence). Read-only, live view: a
   * caller must not mutate or retain a reference across an `update()` call. Used by W3 to
   * build twin pick proxies without duplicating TownAvatars' own bookkeeping. */
  get awayIds(): IterableIterator<string> {
    return this.away.keys();
  }

  /** True while `agentId` is out in town. */
  hasAway(agentId: string): boolean {
    return this.away.has(agentId);
  }

  /** Fills `out` with the twin's current world position and heading and returns true, or
   * returns false without touching `out` when the twin is not away (it left the payload,
   * or it has arrived home and been handed back to the residence) — never reads a handle
   * that has already been disposed (W3-F3). `out` is owned by the caller, so a frame that
   * follows a twin allocates no pose. */
  poseOf(agentId: string, out: { x: number; z: number; heading: number }): boolean {
    const entry = this.away.get(agentId);
    if (!entry) return false;
    out.x = entry.handle.group.position.x;
    out.z = entry.handle.group.position.z;
    out.heading = entry.handle.group.rotation.y;
    return true;
  }

  private advance(agent: WorldAgent, lotOf: ReadonlyMap<string, number>, clock: FrameClock): CommuteState {
    const desired = placeFor(agent);
    const prev = this.commutes.get(agent.agent_id) ?? initCommute(desired, this.town, lotOf);
    const next = stepCommute(prev, desired, agent.agent_id, this.town, lotOf, clock.nowMs, clock.reducedMotion);
    this.commutes.set(agent.agent_id, next);
    return next;
  }

  private updateAway(
    agent: WorldAgent,
    state: AgentState,
    commute: CommuteState,
    clock: FrameClock,
  ): void {
    const entry = this.awayEntry(agent);
    const pose = poseAt(commute, this.town, clock.nowMs, agent.agent_id, entry.commutePose);
    const ride: RideKind | null = commute.path && commute.vehicle !== "walk" ? commute.vehicle : null;
    this.syncVehicle(entry, agent.agent_id, ride);

    const speed = commute.path ? speedOf(commute.vehicle) : 0;
    if (entry.vehicle) updateVehicle(entry.vehicle, pose.x, pose.z, pose.heading, speed * clock.dt);
    entry.handle.floorY = entry.vehicle ? entry.vehicle.seatHeight - RIG_HIP_HEIGHT : 0;

    const riding = entry.vehicle !== null;
    const body = entry.bodyPose;
    body.x = pose.x;
    body.z = pose.z;
    body.heading = pose.heading;
    body.speed = speed;
    body.walking = pose.walking && !riding;
    body.atDesk = riding;
    updateAvatar(entry.handle, entry.anim, state, body, clock.t, clock.dt, clock.reducedMotion);
  }

  private awayEntry(agent: WorldAgent): AwayEntry {
    const existing = this.away.get(agent.agent_id);
    if (existing) return existing;
    const entry: AwayEntry = {
      handle: buildAvatar(this.scene, this.avatarAssets, agent.agent_id, 0),
      anim: createAnimState(agent.agent_id),
      vehicle: null,
      commutePose: { x: 0, z: 0, heading: 0, walking: false, vehicle: "walk" },
      bodyPose: { x: 0, z: 0, heading: 0, speed: 0, walking: false, atDesk: false, phase: "room" },
    };
    this.away.set(agent.agent_id, entry);
    return entry;
  }

  private syncVehicle(entry: AwayEntry, agentId: string, ride: RideKind | null): void {
    if ((entry.vehicle?.kind ?? null) === ride) return;
    entry.vehicle?.dispose();
    entry.vehicle = ride ? buildVehicle(this.scene, this.vehicleAssets, ride, agentId) : null;
  }

  private dropAway(agentId: string): void {
    const entry = this.away.get(agentId);
    if (!entry) return;
    this.release(entry);
    this.away.delete(agentId);
  }

  private release(entry: AwayEntry): void {
    entry.vehicle?.dispose();
    entry.handle.dispose();
  }

  /** An agent that left the roster takes its commute state and away avatar with it. */
  private forgetMissing(agents: readonly WorldAgent[]): void {
    const present = new Set(agents.map((a) => a.agent_id));
    for (const id of [...this.commutes.keys()]) {
      if (present.has(id)) continue;
      this.commutes.delete(id);
      this.dropAway(id);
    }
  }
}

function sameAgents(a: readonly WorldAgent[], b: readonly WorldAgent[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}
