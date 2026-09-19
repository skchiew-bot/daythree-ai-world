/** Third-person camera placement for walk mode (deliverable 3): a spring arm behind the
 * operator that pulls in rather than clipping through a wall. Plain numbers, no three.js.
 * Footprints are few and small, so stepping the arm inward in fixed increments is simpler
 * (and cheap enough) than solving the exact ray-box intersection. */
import type { Footprint } from "./footprints";

export const WALK_ARM_LENGTH_M = 4.5;
export const WALK_ARM_HEIGHT_M = 2.4;
const ARM_STEP_M = 0.25;

export interface ArmOrigin {
  x: number;
  z: number;
  /** Unit direction the arm extends along, from the origin toward the camera. */
  dirX: number;
  dirZ: number;
}

function insideAny(x: number, z: number, footprints: readonly Footprint[]): boolean {
  for (const fp of footprints) {
    if (x >= fp.minX && x <= fp.maxX && z >= fp.minZ && z <= fp.maxZ) return true;
  }
  return false;
}

/** The longest arm length (up to `maxLength`) that never crosses into a footprint,
 * walking outward from the operator and stopping just short of the first one it meets. */
export function armLength(origin: ArmOrigin, footprints: readonly Footprint[], maxLength = WALK_ARM_LENGTH_M): number {
  const steps = Math.max(1, Math.round(maxLength / ARM_STEP_M));
  let free = 0;
  for (let i = 1; i <= steps; i++) {
    const len = (i / steps) * maxLength;
    if (insideAny(origin.x + origin.dirX * len, origin.z + origin.dirZ * len, footprints)) return free;
    free = len;
  }
  return free;
}

export interface CameraPose {
  x: number;
  y: number;
  z: number;
  lookX: number;
  lookY: number;
  lookZ: number;
}

/** The full walk-mode camera pose: behind and above the operator, pulled in by
 * `armLength` when a wall would otherwise clip through it. */
export function walkCameraPose(
  operator: { x: number; z: number; heading: number },
  footprints: readonly Footprint[],
  maxLength = WALK_ARM_LENGTH_M,
  height = WALK_ARM_HEIGHT_M,
): CameraPose {
  const dirX = -Math.sin(operator.heading);
  const dirZ = -Math.cos(operator.heading);
  const len = armLength({ x: operator.x, z: operator.z, dirX, dirZ }, footprints, maxLength);
  return {
    x: operator.x + dirX * len,
    y: height,
    z: operator.z + dirZ * len,
    lookX: operator.x,
    lookY: 1.2,
    lookZ: operator.z,
  };
}
