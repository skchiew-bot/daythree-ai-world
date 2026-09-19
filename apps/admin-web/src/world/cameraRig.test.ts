import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { describe, expect, it, vi } from "vitest";

import { CameraRig } from "./cameraRig";
import { OVERVIEW_POSITION, OVERVIEW_TARGET } from "./sceneSetup";

/** OrbitControls only needs a target it can attach a few listeners to; it never touches
 * anything else on it for construction or `addEventListener("start", ...)`. */
class FakeDomElement {
  addEventListener = vi.fn();
  removeEventListener = vi.fn();
  ownerDocument = { addEventListener: vi.fn(), removeEventListener: vi.fn() };
  style: Record<string, unknown> = {};
  getRootNode() {
    return this;
  }
  setPointerCapture = vi.fn();
  releasePointerCapture = vi.fn();
}

function setup() {
  const camera = new THREE.PerspectiveCamera();
  const controls = new OrbitControls(camera, new FakeDomElement() as unknown as HTMLElement);
  const rig = new CameraRig(camera, controls);
  return { camera, controls, rig };
}

/** ADR-014 W3 review fix: returning to fly must land back at the town overview (the
 * same path "Back to overview" uses), not wherever walk/follow left the camera. This
 * exercises the exact mechanism `runWorld`'s `setMode` now calls on every return to
 * fly: `rig.focus(null, reducedMotion)` followed by repeated `rig.update(dt)`. */
describe("CameraRig.focus(null) returns to the overview (review fix)", () => {
  it("eases the camera and the controls target back to the overview pose", () => {
    const { camera, controls, rig } = setup();
    camera.position.set(0, 1.6, 5); // wherever walk mode last left the camera
    controls.target.set(0, 1, 5);

    rig.focus(null, false);
    for (let i = 0; i < 60; i++) rig.update(0.1);

    expect(camera.position.distanceTo(OVERVIEW_POSITION)).toBeLessThan(0.1);
    expect(controls.target.distanceTo(OVERVIEW_TARGET)).toBeLessThan(0.1);
  });

  it("cuts straight to the overview under reduced motion, with no easing needed", () => {
    const { camera, controls, rig } = setup();
    camera.position.set(0, 1.6, 5);
    controls.target.set(0, 1, 5);

    rig.focus(null, true);

    expect(camera.position.equals(OVERVIEW_POSITION)).toBe(true);
    expect(controls.target.equals(OVERVIEW_TARGET)).toBe(true);
  });
});
