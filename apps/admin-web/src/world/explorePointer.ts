/** Drag-to-turn and click-to-pick on the explore element (deliverable 3, 6): a drag turns
 * the camera heading; a plain click (short travel, short time — same thresholds as the
 * existing building picker) selects a twin instead. `setPointerCapture` is used so a drag
 * that leaves the element boundary keeps delivering move events, and is released on
 * `pointerup`/`pointercancel` (never left dangling). */
export interface PointerTarget {
  addEventListener(type: string, listener: (event: PointerLikeEvent) => void): void;
  removeEventListener(type: string, listener: (event: PointerLikeEvent) => void): void;
  setPointerCapture?: (pointerId: number) => void;
  releasePointerCapture?: (pointerId: number) => void;
}

export interface PointerLikeEvent {
  button: number;
  pointerId: number;
  clientX: number;
  clientY: number;
}

export interface ExplorePointerHandlers {
  /** Called on every pointer move during a drag with the horizontal delta in pixels. */
  onTurn: (deltaX: number) => void;
  /** Called once when a press-release counts as a click rather than a drag. */
  onClick: (clientX: number, clientY: number) => void;
}

const CLICK_MAX_TRAVEL_PX = 5;
const CLICK_MAX_MS = 400;

export function attachExplorePointer(element: PointerTarget, handlers: ExplorePointerHandlers, now: () => number = () => performance.now()): () => void {
  let dragging = false;
  let downX = 0;
  let downY = 0;
  let downAt = 0;
  let travel = 0;
  let lastX = 0;
  let pointerId = -1;

  const onDown = (event: PointerLikeEvent): void => {
    if (event.button !== 0) return;
    dragging = true;
    pointerId = event.pointerId;
    downX = event.clientX;
    downY = event.clientY;
    lastX = event.clientX;
    downAt = now();
    travel = 0;
    element.setPointerCapture?.(pointerId);
  };

  const onMove = (event: PointerLikeEvent): void => {
    if (!dragging) return;
    const deltaX = event.clientX - lastX;
    lastX = event.clientX;
    travel += Math.hypot(event.clientX - downX, event.clientY - downY);
    if (deltaX !== 0) handlers.onTurn(deltaX);
  };

  const end = (event: PointerLikeEvent): void => {
    if (!dragging) return;
    dragging = false;
    element.releasePointerCapture?.(pointerId);
    const isClick = travel <= CLICK_MAX_TRAVEL_PX && now() - downAt <= CLICK_MAX_MS;
    if (isClick) handlers.onClick(event.clientX, event.clientY);
  };

  element.addEventListener("pointerdown", onDown);
  element.addEventListener("pointermove", onMove);
  element.addEventListener("pointerup", end);
  element.addEventListener("pointercancel", end);

  return () => {
    element.removeEventListener("pointerdown", onDown);
    element.removeEventListener("pointermove", onMove);
    element.removeEventListener("pointerup", end);
    element.removeEventListener("pointercancel", end);
  };
}
