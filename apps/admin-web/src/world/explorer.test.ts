import * as THREE from "three";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createAvatarAssets } from "./avatar";
import { Explorer } from "./explorer";

/** A minimal, non-bubbling stand-in for an EventTarget (same shape as keyHeld.test.ts's
 * fake): enough for `attachExploreKeyboard`/`attachExplorePointer`, nothing more. */
class FakeTarget {
  private listeners = new Map<string, Set<(event: never) => void>>();
  hidden = false;

  addEventListener(type: string, listener: (event: never) => void): void {
    const set = this.listeners.get(type) ?? new Set();
    set.add(listener);
    this.listeners.set(type, set);
  }

  removeEventListener(type: string, listener: (event: never) => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  dispatch(type: string, event: unknown): void {
    this.listeners.get(type)?.forEach((fn) => fn(event as never));
  }
}

class FakeElement extends FakeTarget {
  getBoundingClientRect() {
    return { left: 0, top: 0, right: 800, bottom: 600, width: 800, height: 600, x: 0, y: 0, toJSON: () => ({}) };
  }
  setPointerCapture(): void {}
  releasePointerCapture(): void {}
}

function keyEvent(key: string) {
  return { key, preventDefault: vi.fn() };
}

function setup() {
  const win = new FakeTarget();
  const doc = Object.assign(new FakeTarget(), { hidden: false });
  vi.stubGlobal("window", win);
  vi.stubGlobal("document", doc);

  const scene = new THREE.Scene();
  const element = new FakeElement();
  const camera = new THREE.PerspectiveCamera();
  const explorer = new Explorer(scene, createAvatarAssets(), camera, element as unknown as HTMLElement, {
    onEscape: vi.fn(),
    onPickAgent: vi.fn(),
  });
  return { explorer, element, camera };
}

afterEach(() => vi.unstubAllGlobals());

describe("Explorer.clearHeldKeys (deliverable 8, review fix: Esc never blurs the element)", () => {
  it("moves the operator while a key is held", () => {
    const { explorer, element, camera } = setup();
    element.dispatch("keydown", keyEvent("w"));

    const before = camera.position.clone();
    explorer.stepWalk(1, camera);

    expect(camera.position.equals(before)).toBe(false);
  });

  it("holding W, pressing Esc (clearHeldKeys), then re-entering walk does not move the avatar", () => {
    const { explorer, element, camera } = setup();
    element.dispatch("keydown", keyEvent("w"));

    // Esc is handled inside the same keydown listener and never blurs the element, so
    // nothing in keyHeld.ts clears `held.forward` on its own — the mode switch must.
    element.dispatch("keydown", keyEvent("Escape"));
    explorer.clearHeldKeys();

    // First call ever settles the camera into its resting pose regardless of movement;
    // capture the baseline after that, then re-enter walk with no fresh keydown (the
    // physical key was never released or pressed again in this scenario).
    explorer.stepWalk(1, camera);
    const before = camera.position.clone();
    explorer.stepWalk(1, camera);

    expect(camera.position.equals(before)).toBe(true);
  });

  it("a fresh keydown after clearHeldKeys moves the operator again", () => {
    const { explorer, element, camera } = setup();
    element.dispatch("keydown", keyEvent("w"));
    explorer.clearHeldKeys();
    explorer.stepWalk(1, camera); // settle the resting pose before the baseline
    const before = camera.position.clone();

    element.dispatch("keydown", keyEvent("w"));
    explorer.stepWalk(1, camera);

    expect(camera.position.equals(before)).toBe(false);
  });
});
