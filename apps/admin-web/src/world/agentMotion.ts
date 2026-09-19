import type { AgentState } from "./agentState";
import { idleReference, WALK_SPEED } from "./idleSchedule";
import { roomKey } from "./layout";
import { routePoint, type Route } from "./routes";

/** Fastest an avatar may move while catching up with its schedule (e.g. after a tab was
 * hidden, or right after it stopped working). The schedule itself peaks at 1.5x the
 * average speed, so a follower at this cap always tracks it exactly. */
const MAX_SPEED = WALK_SPEED * 2;
const TURN_RATE = 9;
const AT_ROUTE_START = 0.02;
const MOVING_SPEED = 0.05;

export type TravelPhase = "room" | "leave" | "corridor" | "lobby" | "return";

export interface MotionState {
  roomKey: string;
  route: Route;
  /** Distance along `route`: 0 is the desk, `route.idleS` the idle spot. */
  s: number;
  heading: number;
  /** Signed speed along the route in m/s. */
  velocity: number;
}

export interface MotionContext {
  agentId: string;
  floor: number;
  roomIndex: number;
  state: AgentState;
  nowMs: number;
  reducedMotion: boolean;
}

export interface Pose {
  x: number;
  z: number;
  /** Rotation about the y axis; 0 faces +z (towards the camera). */
  heading: number;
  speed: number;
  walking: boolean;
  atDesk: boolean;
  phase: TravelPhase;
}

/** Only an idle agent wanders; every other state keeps it at its desk. */
export function wanders(ctx: MotionContext): boolean {
  return ctx.state === "idle" && !ctx.reducedMotion;
}

function restHeading(s: number): number {
  return s <= AT_ROUTE_START ? Math.PI / 2 : 0;
}

function targetOf(prev: MotionState, ctx: MotionContext): { route: Route; s: number } {
  if (ctx.state !== "idle") return { route: prev.route, s: 0 };
  if (ctx.reducedMotion) return { route: prev.route, s: prev.route.idleS };

  const ref = idleReference(ctx.agentId, ctx.floor, ctx.roomIndex, ctx.nowMs);
  if (ref.route.key === prev.route.key) return ref;
  // A new bucket picked another destination. The room part of every route is shared, so
  // switch as soon as the avatar is back inside; until then keep walking the old one home.
  if (prev.s <= prev.route.idleS + AT_ROUTE_START) return ref;
  return { route: prev.route, s: prev.route.idleS };
}

export function wrapAngle(angle: number): number {
  const turn = Math.PI * 2;
  return angle - turn * Math.floor((angle + Math.PI) / turn);
}

export function turnToward(current: number, target: number, maxStep: number): number {
  const diff = wrapAngle(target - current);
  return wrapAngle(current + Math.min(Math.max(diff, -maxStep), maxStep));
}

/** Places an avatar exactly where its schedule says, with no walking. Used at first
 * sight of an agent and whenever its room changes (ADR-009: a reassigned avatar snaps to
 * its new room instead of crossing the building). */
export function initMotion(ctx: MotionContext): MotionState {
  const key = roomKey(ctx.floor, ctx.roomIndex);
  const ref = idleReference(ctx.agentId, ctx.floor, ctx.roomIndex, ctx.nowMs);
  const s = ctx.state !== "idle" ? 0 : ctx.reducedMotion ? ref.route.idleS : ref.s;
  return { roomKey: key, route: ref.route, s, heading: restHeading(s), velocity: 0 };
}

export function stepMotion(prev: MotionState, ctx: MotionContext, dt: number): MotionState {
  if (prev.roomKey !== roomKey(ctx.floor, ctx.roomIndex)) return initMotion(ctx);

  const target = targetOf(prev, ctx);
  if (ctx.reducedMotion) {
    return { ...prev, route: target.route, s: target.s, heading: restHeading(target.s), velocity: 0 };
  }

  const reach = MAX_SPEED * dt;
  const step = Math.min(Math.max(target.s - prev.s, -reach), reach);
  const s = prev.s + step;
  const moving = Math.abs(step) > 1e-9;
  const desired = moving
    ? headingOf(routePoint(target.route, s), step < 0)
    : restHeading(s);

  return {
    roomKey: prev.roomKey,
    route: target.route,
    s,
    heading: turnToward(prev.heading, desired, TURN_RATE * dt),
    velocity: dt > 0 ? step / dt : 0,
  };
}

function headingOf(at: { dx: number; dz: number }, backwards: boolean): number {
  const sign = backwards ? -1 : 1;
  return Math.atan2(at.dx * sign, at.dz * sign);
}

function phaseOf(state: MotionState): TravelPhase {
  const { route, s, velocity } = state;
  if (Math.abs(velocity) > MOVING_SPEED) {
    if (s <= route.idleS) return "room";
    if (velocity < 0) return "return";
    return s < route.laneS ? "leave" : "corridor";
  }
  return s >= route.laneS ? "lobby" : "room";
}

export function poseOf(state: MotionState): Pose {
  const at = routePoint(state.route, state.s);
  const speed = Math.abs(state.velocity);
  return {
    x: at.x,
    z: at.z,
    heading: state.heading,
    speed,
    walking: speed > MOVING_SPEED,
    atDesk: state.s <= AT_ROUTE_START,
    phase: phaseOf(state),
  };
}
