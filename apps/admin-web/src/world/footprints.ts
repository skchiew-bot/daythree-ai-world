/** Axis-aligned collision footprints for W3 walk mode (deliverable 3): the residence, the
 * community hall, and every project building on its assigned lot. Plain numbers, no
 * three.js, so collision and the "pushed outside a freed lot" rescue stay unit-testable.
 * Recompute only when the project-set signature changes (deliverable 10); the caller owns
 * that memoization the same way `TownScene.sync` does. */
import { buildingSpec } from "./buildingSpec";
import { BUILDING_WIDTH } from "./layout";
import type { WorldProject } from "./renderPayload";
import { allLotSlots, HALL_CENTER, HALL_DEPTH, HALL_WIDTH } from "./town";

export interface Footprint {
  key: string;
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
}

export interface Door {
  key: string;
  x: number;
  z: number;
}

export interface Bounds {
  minX: number;
  maxX: number;
  minZ: number;
  maxZ: number;
}

/** The apartment building (layout.ts): rooms span z in [-1.1, 1.1] and the corridor
 * carries on to z = 2.1; a little padding covers the wall thickness. */
const RESIDENCE_FOOTPRINT: Footprint = {
  key: "residence",
  minX: -BUILDING_WIDTH / 2 - 0.15,
  maxX: BUILDING_WIDTH / 2 + 0.15,
  minZ: -1.3,
  maxZ: 2.25,
};

const BOUNDS_MARGIN_M = 6;

function hallFootprint(): Footprint {
  return {
    key: "hall",
    minX: HALL_CENTER.x - HALL_WIDTH / 2,
    maxX: HALL_CENTER.x + HALL_WIDTH / 2,
    minZ: HALL_CENTER.z - HALL_DEPTH / 2,
    maxZ: HALL_CENTER.z + HALL_DEPTH / 2,
  };
}

/** One rectangle per standing building: the residence, the hall, and every project that
 * has a lot. A project past the 48-lot cap (never happens under the active cap, but an
 * archived-and-still-referenced project could lack one) contributes no rectangle. */
export function footprints(projects: readonly WorldProject[], lotOf: ReadonlyMap<string, number>): Footprint[] {
  const slots = allLotSlots();
  const list: Footprint[] = [RESIDENCE_FOOTPRINT, hallFootprint()];
  for (const project of projects) {
    const lotIndex = lotOf.get(project.id);
    if (lotIndex === undefined) continue;
    const spec = buildingSpec(project.id, lotIndex);
    const { center } = slots[lotIndex];
    list.push({
      key: project.id,
      minX: center.x - spec.width / 2,
      maxX: center.x + spec.width / 2,
      minZ: center.z - spec.depth / 2,
      maxZ: center.z + spec.depth / 2,
    });
  }
  return list;
}

/** The front-door point of every project building, for the proximity card (deliverable 4).
 * The hall and the residence are not included: the proximity card is scoped to project
 * buildings only. */
export function buildingDoors(projects: readonly WorldProject[], lotOf: ReadonlyMap<string, number>): Door[] {
  const slots = allLotSlots();
  const doors: Door[] = [];
  for (const project of projects) {
    const lotIndex = lotOf.get(project.id);
    if (lotIndex === undefined) continue;
    const spec = buildingSpec(project.id, lotIndex);
    const { center } = slots[lotIndex];
    doors.push({ key: project.id, x: center.x, z: center.z + spec.depth / 2 });
  }
  return doors;
}

/** Walkable bounds: every lot plus the hall and the residence, with a fixed margin so the
 * operator can walk the avenues at the town's edge. A pure function of the town's fixed
 * geometry (no projects), so it never needs to be recomputed. */
export function townBounds(): Bounds {
  const slots = allLotSlots();
  let minX = Infinity;
  let maxX = -Infinity;
  let minZ = Infinity;
  let maxZ = -Infinity;
  for (const slot of slots) {
    minX = Math.min(minX, slot.center.x);
    maxX = Math.max(maxX, slot.center.x);
    minZ = Math.min(minZ, slot.center.z);
    maxZ = Math.max(maxZ, slot.center.z);
  }
  return {
    minX: minX - BOUNDS_MARGIN_M,
    maxX: Math.max(maxX, HALL_CENTER.x + HALL_WIDTH / 2) + BOUNDS_MARGIN_M,
    minZ: Math.min(minZ, RESIDENCE_FOOTPRINT.minZ) - BOUNDS_MARGIN_M,
    maxZ: maxZ + BOUNDS_MARGIN_M,
  };
}

/** A stable key for the current project set (id and code): the same signature `TownScene`
 * uses, so the two caches invalidate together. */
export function projectSignature(projects: readonly WorldProject[]): string {
  return projects.map((p) => `${p.id}:${p.code}`).join("|");
}
