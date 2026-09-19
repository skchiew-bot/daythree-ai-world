import {
  CORRIDOR_END_X,
  CORRIDOR_LANE_Z,
  LOBBY_SPOT_XS,
  LOBBY_SPOT_Z,
  roomAnchors,
  type Vec2,
} from "./layout";

export type DestinationKind = "lobby" | "strollLeft" | "strollRight";

export interface Destination {
  kind: DestinationKind;
  /** Index into LOBBY_SPOT_XS; only meaningful for "lobby". */
  spot: number;
}

/** One walkable line: desk -> idle spot -> door -> corridor lane -> destination.
 * An agent's whole position is a single distance `s` along it, which keeps the state
 * machine one-dimensional and stops avatars cutting through walls. The desk/idle/door
 * prefix is identical for every destination of a room, so switching destinations while
 * `s <= idleS` never moves the avatar. */
export interface Route {
  key: string;
  points: readonly Vec2[];
  /** Distance along the route at each point. */
  cumulative: readonly number[];
  length: number;
  /** `s` of the in-room idle spot. */
  idleS: number;
  /** `s` where the route reaches the corridor lane. */
  laneS: number;
}

export interface RoutePoint extends Vec2 {
  /** Unit direction of travel along the route at this point. */
  dx: number;
  dz: number;
}

const MIN_SEGMENT = 1e-3;
const routeCache = new Map<string, Route>();

function destinationPoints(dest: Destination): Vec2[] {
  const x =
    dest.kind === "lobby"
      ? LOBBY_SPOT_XS[dest.spot % LOBBY_SPOT_XS.length]
      : dest.kind === "strollLeft"
        ? -CORRIDOR_END_X
        : CORRIDOR_END_X;
  return [{ x, z: CORRIDOR_LANE_Z }, { x, z: LOBBY_SPOT_Z }];
}

function distance(a: Vec2, b: Vec2): number {
  return Math.hypot(b.x - a.x, b.z - a.z);
}

export function destinationKey(dest: Destination): string {
  return dest.kind === "lobby" ? `lobby:${dest.spot}` : dest.kind;
}

export function buildRoute(roomIndex: number, dest: Destination): Route {
  const key = `${roomIndex}|${destinationKey(dest)}`;
  const cached = routeCache.get(key);
  if (cached) return cached;

  const anchors = roomAnchors(1, roomIndex);
  const doorLane = { x: anchors.door.x, z: CORRIDOR_LANE_Z };
  const points: Vec2[] = [anchors.desk, anchors.idle, anchors.door, doorLane].map((p) => ({ x: p.x, z: p.z }));
  for (const next of destinationPoints(dest)) {
    if (distance(points[points.length - 1], next) > MIN_SEGMENT) points.push(next);
  }

  const cumulative = [0];
  for (let i = 1; i < points.length; i++) cumulative.push(cumulative[i - 1] + distance(points[i - 1], points[i]));

  const route: Route = {
    key,
    points,
    cumulative,
    length: cumulative[cumulative.length - 1],
    idleS: cumulative[1],
    laneS: cumulative[3],
  };
  routeCache.set(key, route);
  return route;
}

export function routePoint(route: Route, s: number): RoutePoint {
  const clamped = Math.min(Math.max(s, 0), route.length);
  let i = 1;
  while (i < route.points.length - 1 && clamped > route.cumulative[i]) i++;
  const a = route.points[i - 1];
  const b = route.points[i];
  const span = route.cumulative[i] - route.cumulative[i - 1];
  const t = span > 0 ? (clamped - route.cumulative[i - 1]) / span : 0;
  const len = distance(a, b) || 1;
  return {
    x: a.x + (b.x - a.x) * t,
    z: a.z + (b.z - a.z) * t,
    dx: (b.x - a.x) / len,
    dz: (b.z - a.z) / len,
  };
}
