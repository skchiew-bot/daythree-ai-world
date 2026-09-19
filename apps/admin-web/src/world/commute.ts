/** Where a twin is and how it gets there (ADR-014 decision 4). A pure state machine: no
 * `Math.random`, no `Date.now()` inside; every input (ids, the town plan, `nowMs`) is passed
 * in, so a test can call it twice and get the same answer.
 *
 * What is and is not the same across browsers: idle wandering (idleSchedule.ts) and building
 * placement (lots.ts) are functions of ids and wall-clock buckets, so two browsers agree. A
 * commute is not: its `startMs` is the local time at which THIS browser first saw the data
 * change, so the timing of a trip depends on each browser's poll phase (a few seconds
 * apart). Making it identical would need a server timestamp, which is not allow-listed. */
import { WALK_SPEED } from "./idleSchedule";
import type { WorldAgent } from "./renderPayload";
import { hashString } from "./rng";
import {
  HALL_NODE,
  pathLength,
  pathPoint,
  type PathPoint,
  RESIDENCE_NODE,
  shortestPath,
  type TownPlan,
  type Vec2,
} from "./town";

export type Place = { kind: "residence" } | { kind: "hall" } | { kind: "project"; projectId: string };

export type VehicleKind = "walk" | "bicycle" | "motorbike";

const BICYCLE_SPEED = 4.2;
const MOTORBIKE_SPEED = 9.5;
const WALK_MAX_M = 14;
const BICYCLE_MAX_M = 40;
/** Keeps pedestrians and vehicles visually off the same line (a sidewalk vs. a lane). */
const LANE_OFFSET_M = 0.6;

export function speedOf(vehicle: VehicleKind): number {
  if (vehicle === "walk") return WALK_SPEED;
  if (vehicle === "bicycle") return BICYCLE_SPEED;
  return MOTORBIKE_SPEED;
}

/** A pure function of trip distance and `agent_id` only (ADR-014 decision 5, D15): never
 * of budget, spend or task count. The +/-3 m jitter is deterministic per agent so two
 * agents making the same trip don't always pick the same vehicle at the boundary. */
export function vehicleFor(distanceMeters: number, agentId: string): VehicleKind {
  const jitter = (hashString(agentId) % 7) - 3;
  const adjusted = distanceMeters + jitter;
  if (adjusted <= WALK_MAX_M) return "walk";
  if (adjusted <= BICYCLE_MAX_M) return "bicycle";
  return "motorbike";
}

/** Where a twin belongs right now (ADR-014 decision 4): at its project's building while
 * `project_id` is set (the server keeps it set through the assigned, working and result-
 * hold phases); at the hall when it has a live task with no project; at the residence when
 * idle. Only these two fields of the allow-listed payload are read. */
export function placeFor(agent: Pick<WorldAgent, "activity" | "project_id">): Place {
  if (agent.project_id) return { kind: "project", projectId: agent.project_id };
  if (agent.activity === "idle") return { kind: "residence" };
  return { kind: "hall" };
}

export function placeKey(place: Place): string {
  return place.kind === "project" ? `project:${place.projectId}` : place.kind;
}

function placeEquals(a: Place, b: Place): boolean {
  return placeKey(a) === placeKey(b);
}

export function resolvePlaceNode(place: Place, town: TownPlan, lotOf: ReadonlyMap<string, number>): string {
  if (place.kind === "residence") return RESIDENCE_NODE;
  if (place.kind === "hall") return HALL_NODE;
  const lotIndex = lotOf.get(place.projectId);
  // No lot assigned (only possible past the 48-active cap, for an archived-and-still-
  // referenced project that never got one): park the twin at the hall rather than crash.
  if (lotIndex === undefined) return HALL_NODE;
  return town.lots[lotIndex].roadNode;
}

export interface CommuteState {
  /** The last place the twin actually arrived at. */
  place: Place;
  /** The road node it stands at (or set off from). Stored, never re-resolved from the current
   * `lotOf`: a project that leaves the list, or a lot that shifts, must not move a twin. */
  placeNode: string;
  /** Where it is headed; equals `place` once arrived. */
  target: Place;
  /** The node the current trip ends at, resolved once when the trip started. */
  targetNode: string;
  /** The road-graph polyline of the current trip, or null when not traveling. */
  path: Vec2[] | null;
  startMs: number;
  distance: number;
  vehicle: VehicleKind;
}

/** Places a twin at `place` with no travel — used the first time an agent is seen, same
 * spirit as agentMotion's initMotion snap (ADR-009), so a fresh page load never shows
 * everyone walking in from the residence. */
export function initCommute(place: Place, town: TownPlan, lotOf: ReadonlyMap<string, number>): CommuteState {
  return settledAt(place, resolvePlaceNode(place, town, lotOf), 0);
}

function settledAt(place: Place, node: string, nowMs: number): CommuteState {
  return { place, placeNode: node, target: place, targetNode: node, path: null, startMs: nowMs, distance: 0, vehicle: "walk" };
}

function travelMs(state: CommuteState): number {
  return (state.distance / speedOf(state.vehicle)) * 1000;
}

/** Advances the commute state machine. `target` is where the current trip ends, and it is
 * never rewritten mid-trip: a change of `desired` while the twin is en route is picked up
 * only once that trip has finished, so the twin never teleports out from under its own path
 * (a task that ends on the way out finishes the walk, then walks home). When free (no trip in
 * progress) and `desired` differs from where it is, it starts a new trip along the shortest
 * road-graph path; a zero-length trip (both places resolve to the same node) arrives at once. */
export function stepCommute(
  prev: CommuteState,
  desired: Place,
  agentId: string,
  town: TownPlan,
  lotOf: ReadonlyMap<string, number>,
  nowMs: number,
  reducedMotion: boolean,
): CommuteState {
  if (reducedMotion) {
    const settled = prev.path === null && placeEquals(prev.place, desired) && placeEquals(prev.target, desired);
    return settled ? prev : settledAt(desired, resolvePlaceNode(desired, town, lotOf), nowMs);
  }

  let state = prev;
  if (state.path && nowMs - state.startMs >= travelMs(state)) {
    state = { ...state, place: state.target, placeNode: state.targetNode, path: null };
  }
  if (state.path || placeEquals(state.place, desired)) return state;

  return startTrip(state, desired, agentId, town, lotOf, nowMs);
}

/** Only the DESTINATION is resolved from `lotOf`; the start is the node the twin already
 * stands at. */
function startTrip(
  from: CommuteState,
  to: Place,
  agentId: string,
  town: TownPlan,
  lotOf: ReadonlyMap<string, number>,
  nowMs: number,
): CommuteState {
  const toNode = resolvePlaceNode(to, town, lotOf);
  const path = from.placeNode === toNode ? null : shortestPath(town.roads, from.placeNode, toNode);
  const distance = path ? pathLength(path) : 0;
  if (!path || distance <= 0) return settledAt(to, toNode, nowMs);
  return {
    place: from.place,
    placeNode: from.placeNode,
    target: to,
    targetNode: toNode,
    path,
    startMs: nowMs,
    distance,
    vehicle: vehicleFor(distance, agentId),
  };
}

export interface CommutePose {
  x: number;
  z: number;
  heading: number;
  walking: boolean;
  vehicle: VehicleKind;
}

const scratchPoint: PathPoint = { x: 0, z: 0, dx: 0, dz: 1 };

/** The twin's position and facing at `nowMs`. A pure function of the state and the clock:
 * calling it twice with the same state and `nowMs` gives the same answer. Pass `out` to reuse
 * one pose object per twin instead of allocating every frame. */
export function poseAt(
  state: CommuteState,
  town: TownPlan,
  nowMs: number,
  agentId: string,
  out: CommutePose = { x: 0, z: 0, heading: 0, walking: false, vehicle: "walk" },
): CommutePose {
  if (!state.path) return standingPose(state, town, agentId, out);

  const elapsedS = Math.max(0, (nowMs - state.startMs) / 1000);
  const s = Math.min(state.distance, elapsedS * speedOf(state.vehicle));
  const at = pathPoint(state.path, s, state.distance, scratchPoint);
  const offset = state.vehicle === "walk" ? LANE_OFFSET_M : -LANE_OFFSET_M;
  out.x = at.x + at.dz * offset;
  out.z = at.z - at.dx * offset;
  out.heading = Math.atan2(at.dx, at.dz);
  out.walking = true;
  out.vehicle = state.vehicle;
  return out;
}

const STAND_SLOTS = 5;
const STAND_SPACING_M = 0.45;

/** Where a twin waits once it has arrived. At a building it faces the door (buildings face
 * +z, so the twin looks toward -z) and takes one of a few slots along the curb, chosen from
 * its id, so several twins at one project don't stand on each other. */
function standingPose(state: CommuteState, town: TownPlan, agentId: string, out: CommutePose): CommutePose {
  const node = town.roads.nodes.get(state.placeNode);
  const x = node?.x ?? 0;
  const z = node?.z ?? 0;
  out.walking = false;
  out.vehicle = "walk";
  if (state.place.kind === "residence") {
    out.x = x;
    out.z = z;
    out.heading = 0;
    return out;
  }
  const slot = (hashString(agentId) % STAND_SLOTS) - (STAND_SLOTS - 1) / 2;
  out.x = x + slot * STAND_SPACING_M;
  out.z = z;
  out.heading = Math.PI;
  return out;
}

export function isArrivedAt(state: CommuteState, place: Place): boolean {
  return state.path === null && placeEquals(state.place, place);
}
