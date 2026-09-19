/** The town plan (ADR-014 decision 4, operator decisions O15-O17): 48 lots on 6 streets
 * of 8, with the residence (the ADR-009 apartment, unmoved) and the community hall
 * anchoring the main street. Plain numbers and a road graph, no three.js, so placement
 * and pathfinding stay unit-testable. */
import { LOBBY_SPOT_Z } from "./layout";

export interface Vec2 {
  x: number;
  z: number;
}

export const LOTS_PER_STREET = 8;
export const STREET_COUNT = 6;
export const LOT_COUNT = LOTS_PER_STREET * STREET_COUNT;
export const MAIN_STREET_INDEX = 0;

export const LOT_WIDTH = 5.6;
export const LOT_DEPTH = 5.6;
const LOT_GAP = 2.4;
export const LOT_SPACING = LOT_WIDTH + LOT_GAP;
const STREET_SPACING = 11;
/** The main street's z. Far enough in front of the residence that its buildings (up to
 * ~7.5 m) do not hide the apartment from a raised camera, and clear of the row of external
 * avatars standing in front of it (externalAvatars.ts EXTERNAL_ROW_Z). Buildings sit on the
 * far (-z) side of each street and face +z, the same way the apartment's open fronts face. */
const TOWN_Z_START = 22;
const AVENUE_MARGIN = 4;
export const ROAD_HALF_WIDTH = 1.2;
const SIDEWALK_WIDTH = 0.6;
/** How far a building's footprint center sits behind (-z of) the street spine: road,
 * sidewalk, then half the lot depth, so buildings never straddle the road. */
const LOT_SETBACK = ROAD_HALF_WIDTH + SIDEWALK_WIDTH + LOT_DEPTH / 2;

function streetHalfLength(): number {
  return (LOTS_PER_STREET * LOT_SPACING) / 2;
}

export function streetZ(street: number): number {
  return TOWN_Z_START + street * STREET_SPACING;
}

export function lotFrontX(lotInStreet: number): number {
  return -streetHalfLength() + LOT_SPACING / 2 + lotInStreet * LOT_SPACING;
}

export const RESIDENCE_NODE = "residence";
/** The junction where the residence's spur meets the main street, in the gap between the
 * two lots either side of x = 0. */
const GATE_NODE = "gate";
export const HALL_NODE = "hall";
/** Where the residence's front door meets the road (layout.ts's lobby apron, offset
 * clear of the building so the two never visually overlap). */
export const RESIDENCE_ENTRANCE: Vec2 = { x: 0, z: LOBBY_SPOT_Z + 1.5 };
/** The hall's door meets the main street's east spur here. */
export const HALL_POSITION: Vec2 = { x: streetHalfLength() + AVENUE_MARGIN + 10, z: streetZ(MAIN_STREET_INDEX) };
export const HALL_WIDTH = 9;
export const HALL_DEPTH = 7;
export const HALL_CENTER: Vec2 = {
  x: HALL_POSITION.x,
  z: HALL_POSITION.z - (ROAD_HALF_WIDTH + SIDEWALK_WIDTH + HALL_DEPTH / 2),
};

export interface LotSlot {
  index: number;
  street: number;
  lotInStreet: number;
  /** Building footprint center. */
  center: Vec2;
  /** Where the building's driveway meets the street spine. */
  roadNode: string;
}

function westEndNode(street: number): string {
  return `w${street}`;
}
function eastEndNode(street: number): string {
  return `e${street}`;
}
function lotNode(street: number, lotInStreet: number): string {
  return `lot-${street}-${lotInStreet}`;
}

export function allLotSlots(): LotSlot[] {
  const slots: LotSlot[] = [];
  for (let street = 0; street < STREET_COUNT; street++) {
    for (let lotInStreet = 0; lotInStreet < LOTS_PER_STREET; lotInStreet++) {
      slots.push({
        index: street * LOTS_PER_STREET + lotInStreet,
        street,
        lotInStreet,
        center: { x: lotFrontX(lotInStreet), z: streetZ(street) - LOT_SETBACK },
        roadNode: lotNode(street, lotInStreet),
      });
    }
  }
  return slots;
}

export interface RoadGraph {
  nodes: ReadonlyMap<string, Vec2>;
  edges: ReadonlyMap<string, readonly { to: string; dist: number }[]>;
}

export interface TownPlan {
  lots: readonly LotSlot[];
  roads: RoadGraph;
}

function distance(a: Vec2, b: Vec2): number {
  return Math.hypot(b.x - a.x, b.z - a.z);
}

class GraphBuilder {
  private readonly nodes = new Map<string, Vec2>();
  private readonly edges = new Map<string, { to: string; dist: number }[]>();

  node(id: string, at: Vec2): void {
    this.nodes.set(id, at);
  }

  edge(a: string, b: string): void {
    const dist = distance(this.at(a), this.at(b));
    this.push(a, b, dist);
    this.push(b, a, dist);
  }

  build(): RoadGraph {
    return { nodes: this.nodes, edges: this.edges };
  }

  private at(id: string): Vec2 {
    const point = this.nodes.get(id);
    if (!point) throw new Error(`Unknown road node "${id}"`);
    return point;
  }

  private push(a: string, b: string, dist: number): void {
    const list = this.edges.get(a) ?? [];
    list.push({ to: b, dist });
    this.edges.set(a, list);
  }
}

/** Builds the road graph once: a spine per street, a west and east avenue tying every
 * street together (so any lot reaches any other, and the residence and hall reach every
 * lot), a straight spur from the residence down to the main street's gate, and one from the hall
 * onto the main street's east end. */
export function buildTownPlan(): TownPlan {
  const lots = allLotSlots();
  const g = new GraphBuilder();

  g.node(RESIDENCE_NODE, RESIDENCE_ENTRANCE);
  g.node(HALL_NODE, HALL_POSITION);

  for (let street = 0; street < STREET_COUNT; street++) {
    const z = streetZ(street);
    const west = { x: -streetHalfLength() - AVENUE_MARGIN, z };
    const east = { x: streetHalfLength() + AVENUE_MARGIN, z };
    g.node(westEndNode(street), west);
    g.node(eastEndNode(street), east);

    let prev = westEndNode(street);
    for (let lotInStreet = 0; lotInStreet < LOTS_PER_STREET; lotInStreet++) {
      const id = lotNode(street, lotInStreet);
      g.node(id, { x: lotFrontX(lotInStreet), z });
      if (street === MAIN_STREET_INDEX && lotInStreet === LOTS_PER_STREET / 2) {
        g.node(GATE_NODE, { x: 0, z });
        g.edge(prev, GATE_NODE);
        prev = GATE_NODE;
      }
      g.edge(prev, id);
      prev = id;
    }
    g.edge(prev, eastEndNode(street));
  }

  for (let street = 0; street < STREET_COUNT - 1; street++) {
    g.edge(westEndNode(street), westEndNode(street + 1));
    g.edge(eastEndNode(street), eastEndNode(street + 1));
  }

  g.edge(RESIDENCE_NODE, GATE_NODE);
  g.edge(HALL_NODE, eastEndNode(MAIN_STREET_INDEX));

  return { lots, roads: g.build() };
}

/** Dijkstra over the (small, static) road graph. Returns the polyline of waypoints from
 * `from` to `to`, or null if either node is unknown (never happens for a built TownPlan). */
export function shortestPath(graph: RoadGraph, from: string, to: string): Vec2[] | null {
  if (!graph.nodes.has(from) || !graph.nodes.has(to)) return null;
  if (from === to) return [graph.nodes.get(from)!];

  const dist = new Map<string, number>([[from, 0]]);
  const prev = new Map<string, string>();
  const visited = new Set<string>();

  for (;;) {
    let current: string | null = null;
    let best = Infinity;
    for (const [id, d] of dist) {
      if (!visited.has(id) && d < best) {
        best = d;
        current = id;
      }
    }
    if (current === null) break;
    if (current === to) break;
    visited.add(current);

    for (const { to: neighbor, dist: edgeDist } of graph.edges.get(current) ?? []) {
      const candidate = best + edgeDist;
      if (candidate < (dist.get(neighbor) ?? Infinity)) {
        dist.set(neighbor, candidate);
        prev.set(neighbor, current);
      }
    }
  }

  if (!dist.has(to)) return null;
  const path: string[] = [to];
  let cursor = to;
  while (cursor !== from) {
    const before = prev.get(cursor);
    if (!before) return null;
    path.push(before);
    cursor = before;
  }
  path.reverse();
  return path.map((id) => graph.nodes.get(id)!);
}

export function pathLength(points: readonly Vec2[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i++) total += distance(points[i - 1], points[i]);
  return total;
}

export interface PathPoint extends Vec2 {
  dx: number;
  dz: number;
}

/** A point at distance `s` along a polyline, with the unit direction of travel there
 * (mirrors routes.ts's routePoint, generalized to an arbitrary road-graph path). Pass the
 * path's `total` length and a reusable `out` to keep a per-frame call allocation-free. */
export function pathPoint(
  points: readonly Vec2[],
  s: number,
  total: number = pathLength(points),
  out: PathPoint = { x: 0, z: 0, dx: 0, dz: 1 },
): PathPoint {
  if (points.length === 0) return set(out, 0, 0, 0, 1);
  if (points.length === 1) return set(out, points[0].x, points[0].z, 0, 1);

  const clamped = Math.min(Math.max(s, 0), total);
  let covered = 0;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    const segLen = distance(a, b);
    if (clamped <= covered + segLen || i === points.length - 1) {
      const t = segLen > 0 ? (clamped - covered) / segLen : 0;
      const len = segLen || 1;
      return set(out, a.x + (b.x - a.x) * t, a.z + (b.z - a.z) * t, (b.x - a.x) / len, (b.z - a.z) / len);
    }
    covered += segLen;
  }
  const last = points[points.length - 1];
  return set(out, last.x, last.z, 0, 1);
}

function set(out: PathPoint, x: number, z: number, dx: number, dz: number): PathPoint {
  out.x = x;
  out.z = z;
  out.dx = dx;
  out.dz = dz;
  return out;
}
