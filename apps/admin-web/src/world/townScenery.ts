import type { GeometryBatcher } from "./batch";
import { hashString } from "./rng";
import {
  LOT_DEPTH,
  LOT_SPACING,
  LOT_WIDTH,
  LOTS_PER_STREET,
  lotFrontX,
  MAIN_STREET_INDEX,
  ROAD_HALF_WIDTH,
  streetZ,
  STREET_COUNT,
  type RoadGraph,
  type TownPlan,
} from "./town";

const ROAD_HEIGHT = 0.04;
const SIDEWALK_HEIGHT = 0.06;
const SIDEWALK_WIDTH = 0.6;
const LINE_WIDTH = 0.1;
const LAMP_HEIGHT = 1.9;

/** One strip per road edge, each undirected edge once. Every edge in the plan is axis-
 * aligned, but the rotation is general so a future diagonal road still lines up. */
function addRoads(b: GeometryBatcher, roads: RoadGraph): void {
  const drawn = new Set<string>();
  for (const [from, list] of roads.edges) {
    for (const { to, dist } of list) {
      const key = from < to ? `${from}|${to}` : `${to}|${from}`;
      if (drawn.has(key)) continue;
      drawn.add(key);

      const a = roads.nodes.get(from)!;
      const c = roads.nodes.get(to)!;
      const ry = Math.atan2(-(c.z - a.z), c.x - a.x);
      const mx = (a.x + c.x) / 2;
      const mz = (a.z + c.z) / 2;
      b.box("asphalt", dist, ROAD_HEIGHT, ROAD_HALF_WIDTH * 2, mx, ROAD_HEIGHT / 2, mz, { ry });
      b.box("laneLine", dist, ROAD_HEIGHT + 0.005, LINE_WIDTH, mx, ROAD_HEIGHT / 2 + 0.003, mz, { ry });
    }
  }
}

/** A pad under every lot, occupied or not, so the whole grid reads as a town that has
 * room to grow. The sidewalk runs along the lot side of each street. */
function addLotsAndSidewalks(b: GeometryBatcher, plan: TownPlan): void {
  for (const lot of plan.lots) {
    b.box("lotPad", LOT_WIDTH, 0.05, LOT_DEPTH, lot.center.x, 0.025, lot.center.z);
  }
  const length = LOTS_PER_STREET * LOT_SPACING;
  for (let street = 0; street < STREET_COUNT; street++) {
    const z = streetZ(street) - (ROAD_HALF_WIDTH + SIDEWALK_WIDTH / 2);
    b.box("sidewalk", length, SIDEWALK_HEIGHT, SIDEWALK_WIDTH, 0, SIDEWALK_HEIGHT / 2, z);
  }
}

function addLamp(b: GeometryBatcher, x: number, z: number): void {
  b.cylinder("metal", 0.05, 0.06, LAMP_HEIGHT, x, LAMP_HEIGHT / 2, z, 8);
  b.sphere("lampGlow", 0.14, x, LAMP_HEIGHT + 0.1, z);
}

function addTree(b: GeometryBatcher, x: number, z: number, scale: number): void {
  b.cylinder("trunk", 0.07 * scale, 0.09 * scale, 0.9 * scale, x, 0.45 * scale, z, 7);
  b.sphere("foliage", 0.55 * scale, x, 1.15 * scale, z);
  b.sphere("foliage2", 0.38 * scale, x + 0.12 * scale, 1.5 * scale, z - 0.08 * scale);
}

export interface Furniture {
  kind: "lamp" | "tree";
  x: number;
  z: number;
  scale: number;
}

/** Street lamps in every gap between lots, and a tree behind most gaps; which gaps get a
 * tree is a function of the lot's grid position, never of what stands on it. The main
 * street's x = 0 gap carries the residence's spur road, so it gets neither: commuters ride
 * straight through it. */
export function streetFurniture(): Furniture[] {
  const items: Furniture[] = [];
  for (let street = 0; street < STREET_COUNT; street++) {
    const lampZ = streetZ(street) - (ROAD_HALF_WIDTH + SIDEWALK_WIDTH / 2);
    for (let i = 0; i <= LOTS_PER_STREET; i++) {
      const gapX = lotFrontX(0) - LOT_SPACING / 2 + i * LOT_SPACING;
      if (street === MAIN_STREET_INDEX && Math.abs(gapX) < 1e-6) continue;
      items.push({ kind: "lamp", x: gapX, z: lampZ, scale: 1 });
      const roll = hashString(`tree:${street}:${i}`) % 3;
      if (roll !== 0) items.push({ kind: "tree", x: gapX, z: streetZ(street) - 8.3, scale: 0.85 + roll * 0.12 });
    }
  }
  return items;
}

function addStreetFurniture(b: GeometryBatcher): void {
  for (const item of streetFurniture()) {
    if (item.kind === "lamp") addLamp(b, item.x, item.z);
    else addTree(b, item.x, item.z, item.scale);
  }
}

export function addTownScenery(b: GeometryBatcher, plan: TownPlan): void {
  addRoads(b, plan.roads);
  addLotsAndSidewalks(b, plan);
  addStreetFurniture(b);
}
