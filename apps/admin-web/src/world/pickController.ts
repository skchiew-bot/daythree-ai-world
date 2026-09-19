import * as THREE from "three";

const CLICK_MAX_TRAVEL_PX = 5;
const CLICK_MAX_MS = 400;

/** Turns a click (not a drag: OrbitControls owns drags) on the canvas into the key of the
 * building under the cursor. Returns a function that removes its listeners. */
export function attachPicking(
  element: HTMLElement,
  camera: THREE.Camera,
  pickables: () => readonly THREE.Object3D[],
  onPick: (key: string) => void,
): () => void {
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  let downX = 0;
  let downY = 0;
  let downAt = 0;
  let downValid = false;

  const onDown = (event: PointerEvent): void => {
    if (event.button !== 0) return;
    downValid = true;
    downX = event.clientX;
    downY = event.clientY;
    downAt = performance.now();
  };

  const onUp = (event: PointerEvent): void => {
    // Only a primary-button press that started on the canvas counts as a click.
    if (event.button !== 0 || !downValid) return;
    downValid = false;
    const travel = Math.hypot(event.clientX - downX, event.clientY - downY);
    if (travel > CLICK_MAX_TRAVEL_PX || performance.now() - downAt > CLICK_MAX_MS) return;

    const rect = element.getBoundingClientRect();
    ndc.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(ndc, camera);
    const hit = raycaster.intersectObjects(pickables() as THREE.Object3D[], false)[0];
    const key = hit?.object.userData.key;
    if (typeof key === "string") onPick(key);
  };

  element.addEventListener("pointerdown", onDown);
  element.addEventListener("pointerup", onUp);
  return () => {
    element.removeEventListener("pointerdown", onDown);
    element.removeEventListener("pointerup", onUp);
  };
}
