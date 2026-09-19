/** Frame-rate independent operator movement for W3 walk mode (deliverable 3). Plain
 * numbers, no three.js: displacement is `speed * dt` along the held directions, so two
 * frames at half the size cover the same ground as one at full size. WASD/arrows move
 * relative to the current heading; turning itself comes only from the drag gesture
 * (`headingDelta`), never from A/D, so strafing and turning stay independent. */
import { WALK_SPEED } from "./idleSchedule";

export const RUN_MULTIPLIER = 2.4;

export interface WalkKeys {
  forward: boolean;
  backward: boolean;
  left: boolean;
  right: boolean;
  running: boolean;
}

export interface WalkState {
  x: number;
  z: number;
  heading: number;
}

export const NO_KEYS: WalkKeys = { forward: false, backward: false, left: false, right: false, running: false };

/** Advances the walk state by `dt` seconds. `headingDelta` (radians) is applied before
 * movement, so a drag-and-move in the same frame turns first, then walks the new way. */
export function stepWalk(state: WalkState, keys: WalkKeys, headingDelta: number, dt: number): WalkState {
  const heading = state.heading + headingDelta;
  let moveX = 0;
  let moveZ = 0;
  if (keys.forward) {
    moveX += Math.sin(heading);
    moveZ += Math.cos(heading);
  }
  if (keys.backward) {
    moveX -= Math.sin(heading);
    moveZ -= Math.cos(heading);
  }
  if (keys.left) {
    moveX -= Math.cos(heading);
    moveZ += Math.sin(heading);
  }
  if (keys.right) {
    moveX += Math.cos(heading);
    moveZ -= Math.sin(heading);
  }

  const len = Math.hypot(moveX, moveZ);
  if (len === 0) return { x: state.x, z: state.z, heading };

  const speed = (keys.running ? WALK_SPEED * RUN_MULTIPLIER : WALK_SPEED) * dt;
  return { x: state.x + (moveX / len) * speed, z: state.z + (moveZ / len) * speed, heading };
}

export function isMoving(keys: WalkKeys): boolean {
  return keys.forward || keys.backward || keys.left || keys.right;
}
