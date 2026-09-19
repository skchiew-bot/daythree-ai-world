import { describe, expect, it, vi } from "vitest";

import { attachExplorePointer, type PointerLikeEvent } from "./explorePointer";

class FakeElement {
  private listeners = new Map<string, Set<(event: PointerLikeEvent) => void>>();
  setPointerCapture = vi.fn();
  releasePointerCapture = vi.fn();

  addEventListener(type: string, listener: (event: PointerLikeEvent) => void): void {
    const set = this.listeners.get(type) ?? new Set();
    set.add(listener);
    this.listeners.set(type, set);
  }

  removeEventListener(type: string, listener: (event: PointerLikeEvent) => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  dispatch(type: string, event: PointerLikeEvent): void {
    this.listeners.get(type)?.forEach((fn) => fn(event));
  }
}

function pointer(x: number, y: number, id = 1): PointerLikeEvent {
  return { button: 0, pointerId: id, clientX: x, clientY: y };
}

describe("attachExplorePointer (deliverable 3 drag-to-turn, deliverable 6 pick-by-mode, test 5)", () => {
  it("turns on every move once a drag has started, and captures the pointer", () => {
    const element = new FakeElement();
    const onTurn = vi.fn();
    const onClick = vi.fn();
    attachExplorePointer(element, { onTurn, onClick }, () => 0);

    element.dispatch("pointerdown", pointer(0, 0));
    element.dispatch("pointermove", pointer(10, 0));

    expect(onTurn).toHaveBeenCalledWith(10);
    expect(element.setPointerCapture).toHaveBeenCalledWith(1);
  });

  it("test 5: a short click (little travel, little time) calls onClick, not onTurn's drag path", () => {
    const element = new FakeElement();
    const onTurn = vi.fn();
    const onClick = vi.fn();
    let now = 0;
    attachExplorePointer(element, { onTurn, onClick }, () => now);

    element.dispatch("pointerdown", pointer(100, 100));
    now = 50;
    element.dispatch("pointerup", pointer(100, 100));

    expect(onClick).toHaveBeenCalledWith(100, 100);
    expect(onTurn).not.toHaveBeenCalled();
  });

  it("test 5: a drag-end (large travel) release never calls onClick", () => {
    const element = new FakeElement();
    const onTurn = vi.fn();
    const onClick = vi.fn();
    attachExplorePointer(element, { onTurn, onClick }, () => 0);

    element.dispatch("pointerdown", pointer(0, 0));
    element.dispatch("pointermove", pointer(80, 0));
    element.dispatch("pointerup", pointer(80, 0));

    expect(onClick).not.toHaveBeenCalled();
  });

  it("a long-held press past the click time window is not treated as a click", () => {
    const element = new FakeElement();
    const onClick = vi.fn();
    let now = 0;
    attachExplorePointer(element, { onTurn: vi.fn(), onClick }, () => now);

    element.dispatch("pointerdown", pointer(0, 0));
    now = 1000;
    element.dispatch("pointerup", pointer(0, 0));

    expect(onClick).not.toHaveBeenCalled();
  });

  it("releases the pointer capture on pointerup and on pointercancel", () => {
    const element = new FakeElement();
    attachExplorePointer(element, { onTurn: vi.fn(), onClick: vi.fn() }, () => 0);

    element.dispatch("pointerdown", pointer(0, 0));
    element.dispatch("pointercancel", pointer(0, 0));

    expect(element.releasePointerCapture).toHaveBeenCalledWith(1);
  });

  it("dispose removes every listener", () => {
    const element = new FakeElement();
    const removeSpy = vi.spyOn(element, "removeEventListener");
    const dispose = attachExplorePointer(element, { onTurn: vi.fn(), onClick: vi.fn() }, () => 0);

    dispose();

    expect(removeSpy).toHaveBeenCalledTimes(4);
  });
});
