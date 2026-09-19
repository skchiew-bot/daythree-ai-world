/** Circle-vs-axis-aligned-rectangle collision for the W3 operator avatar (deliverable 3).
 * Plain numbers, no three.js. `resolvePosition` is used every walk frame; `pushOutside` is
 * used once after a town sync to rescue an operator standing on a lot a shifted project
 * just filled (deliverable 3, W3-F6). */
import type { Bounds, Footprint } from "./footprints";

export const OPERATOR_RADIUS_M = 0.35;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function pushOutOfRect(x: number, z: number, radius: number, fp: Footprint): { x: number; z: number } {
  const closestX = clamp(x, fp.minX, fp.maxX);
  const closestZ = clamp(z, fp.minZ, fp.maxZ);
  const dx = x - closestX;
  const dz = z - closestZ;
  const distSq = dx * dx + dz * dz;
  if (distSq > radius * radius) return { x, z };
  if (distSq > 1e-9) {
    const dist = Math.sqrt(distSq);
    return { x: closestX + (dx / dist) * radius, z: closestZ + (dz / dist) * radius };
  }
  return pushToNearestEdge(x, z, radius, fp);
}

/** The center is inside the rectangle: step out through the closest wall. */
function pushToNearestEdge(x: number, z: number, radius: number, fp: Footprint): { x: number; z: number } {
  const distLeft = x - fp.minX;
  const distRight = fp.maxX - x;
  const distTop = z - fp.minZ;
  const distBottom = fp.maxZ - z;
  const min = Math.min(distLeft, distRight, distTop, distBottom);
  if (min === distLeft) return { x: fp.minX - radius, z };
  if (min === distRight) return { x: fp.maxX + radius, z };
  if (min === distTop) return { x, z: fp.minZ - radius };
  return { x, z: fp.maxZ + radius };
}

/** Pushes (x, z) out of every footprint it overlaps, applied one rectangle at a time.
 * Footprints are spaced well apart (lots, the hall, the residence), so one pass settles
 * the point outside all of them; a second pass costs little and guards the rare case
 * where pushing out of one rectangle lands inside a neighbour. */
export function resolvePosition(
  x: number,
  z: number,
  footprints: readonly Footprint[],
  radius: number = OPERATOR_RADIUS_M,
): { x: number; z: number } {
  let rx = x;
  let rz = z;
  for (let pass = 0; pass < 2; pass++) {
    for (const fp of footprints) {
      const pushed = pushOutOfRect(rx, rz, radius, fp);
      rx = pushed.x;
      rz = pushed.z;
    }
  }
  return { x: rx, z: rz };
}

/** True when (x, z) sits inside any footprint, ignoring the collision radius — used to
 * detect the freed-lot rescue case (W3-F6) before pushing out. */
export function isInsideAny(x: number, z: number, footprints: readonly Footprint[]): boolean {
  return footprints.some((fp) => x >= fp.minX && x <= fp.maxX && z >= fp.minZ && z <= fp.maxZ);
}

export function clampToBounds(x: number, z: number, bounds: Bounds, margin = 0): { x: number; z: number } {
  return {
    x: clamp(x, bounds.minX + margin, bounds.maxX - margin),
    z: clamp(z, bounds.minZ + margin, bounds.maxZ - margin),
  };
}
