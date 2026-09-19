/** Finds the nearest building door within range of the operator (deliverable 4). Plain
 * numbers, no three.js. */
import type { Door } from "./footprints";

export const PROXIMITY_RADIUS_M = 3;

export interface NearestDoor {
  key: string;
  distance: number;
}

export function nearestDoor(x: number, z: number, doors: readonly Door[], radius = PROXIMITY_RADIUS_M): NearestDoor | null {
  let best: NearestDoor | null = null;
  for (const door of doors) {
    const distance = Math.hypot(x - door.x, z - door.z);
    if (distance <= radius && (!best || distance < best.distance)) best = { key: door.key, distance };
  }
  return best;
}
