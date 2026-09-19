/** What a project building looks like, as plain numbers (no three.js). Variety comes only
 * from the project's id and its lot (ADR-014 decision 5, data-warden D15): never from
 * budget, spend, deal size, task count, status or the project's name or code, so a
 * screenshot of the town never leaks anything about a client. */
import { hashString } from "./rng";
import { LOT_WIDTH } from "./town";

export type RoofStyle = "flat" | "pyramid" | "step";

export const ROOF_STYLES: readonly RoofStyle[] = ["flat", "pyramid", "step"];
export const PALETTE_COUNT = 8;
export const FLOOR_HEIGHT_M = 1.5;

export interface BuildingSpec {
  floors: number;
  width: number;
  depth: number;
  roof: RoofStyle;
  palette: number;
}

const MIN_FLOORS = 2;
const FLOOR_SPAN = 4;
const MIN_FOOTPRINT = 0.72;
const FOOTPRINT_STEP = 0.06;

/** A pure function of (projectId, lotIndex). `lotIndex` shifts the palette so neighbours
 * on a street differ even when two ids happen to hash alike. */
export function buildingSpec(projectId: string, lotIndex: number): BuildingSpec {
  const h = hashString(projectId);
  const widthScale = MIN_FOOTPRINT + ((h >>> 3) % 4) * FOOTPRINT_STEP;
  const depthScale = MIN_FOOTPRINT + ((h >>> 6) % 4) * FOOTPRINT_STEP;
  return {
    floors: MIN_FLOORS + (h % FLOOR_SPAN),
    width: LOT_WIDTH * widthScale,
    depth: LOT_WIDTH * depthScale,
    roof: ROOF_STYLES[(h >>> 9) % ROOF_STYLES.length],
    palette: ((h >>> 12) + lotIndex) % PALETTE_COUNT,
  };
}

export function buildingHeight(spec: BuildingSpec): number {
  return spec.floors * FLOOR_HEIGHT_M;
}
