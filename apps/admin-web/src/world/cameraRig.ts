import * as THREE from "three";
import type { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import type { BuildingPick } from "./buildings";
import { OVERVIEW_POSITION, OVERVIEW_TARGET } from "./sceneSetup";

const EASE_RATE = 4;
const SETTLE_DISTANCE = 0.05;
/** Raised enough to see over the street of buildings in front of the focused one. */
const FOCUS_OFFSET = new THREE.Vector3(3, 12, 11);

/** Eases the camera between the town overview and a focused building. Orbiting by hand
 * cancels an in-flight move so the user is never fought. With reduced motion the camera
 * jumps instead of gliding. */
export class CameraRig {
  private readonly goalPosition = OVERVIEW_POSITION.clone();
  private readonly goalTarget = OVERVIEW_TARGET.clone();
  private moving = false;
  private readonly cancel = (): void => {
    this.moving = false;
  };

  constructor(
    private readonly camera: THREE.PerspectiveCamera,
    private readonly controls: OrbitControls,
  ) {
    controls.addEventListener("start", this.cancel);
  }

  /** Cancels any in-flight ease without moving the camera (W3 deliverable 2: entering
   * walk or follow must cancel a rig ease already underway). */
  cancelMove(): void {
    this.moving = false;
  }

  /** Focus a building, or pass null to return to the overview. */
  focus(pick: BuildingPick | null, reducedMotion: boolean): void {
    if (pick) {
      this.goalTarget.set(pick.x, pick.height / 2, pick.z);
      this.goalPosition.copy(this.goalTarget).add(FOCUS_OFFSET);
    } else {
      this.goalTarget.copy(OVERVIEW_TARGET);
      this.goalPosition.copy(OVERVIEW_POSITION);
    }
    if (reducedMotion) {
      this.camera.position.copy(this.goalPosition);
      this.controls.target.copy(this.goalTarget);
      this.moving = false;
      return;
    }
    this.moving = true;
  }

  update(dt: number): void {
    if (!this.moving) return;
    const t = 1 - Math.exp(-EASE_RATE * dt);
    this.camera.position.lerp(this.goalPosition, t);
    this.controls.target.lerp(this.goalTarget, t);
    const close =
      this.camera.position.distanceTo(this.goalPosition) < SETTLE_DISTANCE &&
      this.controls.target.distanceTo(this.goalTarget) < SETTLE_DISTANCE;
    if (close) this.moving = false;
  }

  dispose(): void {
    this.controls.removeEventListener("start", this.cancel);
  }
}
