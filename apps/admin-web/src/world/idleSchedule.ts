import { LOBBY_SPOT_XS } from "./layout";
import { hashString, seededRandom } from "./rng";
import { buildRoute, type Destination, type Route } from "./routes";

/** Wall-clock bucket length. Each agent draws one wander plan per bucket from a PRNG
 * keyed by (agent_id, bucket), so two browsers agree on who is where without any
 * network traffic. Trips finish inside their own bucket. */
export const BUCKET_MS = 40_000;
/** Average walking speed in metres per second. */
export const WALK_SPEED = 1.1;

const GO_PROBABILITY = 0.9;
const DWELL_MIN_MS = 4_000;
const DWELL_SPAN_MS = 5_000;
const LOBBY_SHARE = 0.7;
const STROLL_LEFT_SHARE = 0.85;

export interface TripPlan {
  goes: boolean;
  /** Start of the trip, in ms after the bucket begins. */
  startMs: number;
  outMs: number;
  dwellMs: number;
  totalMs: number;
  route: Route;
}

export interface IdleReference {
  route: Route;
  /** Where along `route` an idle agent should be at this instant. */
  s: number;
}

function pickDestination(pick: number, floor: number, roomIndex: number, bucket: number): Destination {
  // Lobby places rotate with the room index and a per-floor, per-bucket shift, so the
  // (at most four) agents of one floor never stand on the same place.
  const places = LOBBY_SPOT_XS.length;
  const shift = hashString(`${floor}:${bucket}`) % places;
  if (pick < LOBBY_SHARE) return { kind: "lobby", spot: (roomIndex - 1 + shift) % places };
  return { kind: pick < STROLL_LEFT_SHARE ? "strollLeft" : "strollRight", spot: 0 };
}

export function planTrip(agentId: string, floor: number, roomIndex: number, bucket: number): TripPlan {
  const rng = seededRandom(`${agentId}|${bucket}`);
  const goes = rng() < GO_PROBABILITY;
  const startFraction = rng();
  const dwellMs = DWELL_MIN_MS + rng() * DWELL_SPAN_MS;
  const route = buildRoute(roomIndex, pickDestination(rng(), floor, roomIndex, bucket));

  const outMs = ((route.length - route.idleS) / WALK_SPEED) * 1000;
  const totalMs = 2 * outMs + dwellMs;
  const startMs = startFraction * Math.max(0, BUCKET_MS - totalMs);
  return { goes, startMs, outMs, dwellMs, totalMs, route };
}

function smoothstep(x: number): number {
  const c = Math.min(Math.max(x, 0), 1);
  return c * c * (3 - 2 * c);
}

/** Where an idle agent belongs at `nowMs`: in the room, easing out to the destination,
 * dwelling there, then easing back. A pure function of its arguments. */
export function idleReference(agentId: string, floor: number, roomIndex: number, nowMs: number): IdleReference {
  const bucket = Math.floor(nowMs / BUCKET_MS);
  const plan = planTrip(agentId, floor, roomIndex, bucket);
  const { route } = plan;
  const local = nowMs - bucket * BUCKET_MS - plan.startMs;
  const reach = route.length - route.idleS;

  if (!plan.goes || local < 0 || local >= plan.totalMs) return { route, s: route.idleS };
  if (local < plan.outMs) return { route, s: route.idleS + reach * smoothstep(local / plan.outMs) };
  if (local < plan.outMs + plan.dwellMs) return { route, s: route.length };
  const back = (local - plan.outMs - plan.dwellMs) / plan.outMs;
  return { route, s: route.length - reach * smoothstep(back) };
}
