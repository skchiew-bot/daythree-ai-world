import { describe, expect, it, vi } from "vitest";

import { attachExploreKeyboard, type KeyLikeEvent } from "./keyHeld";

/** A minimal, non-bubbling stand-in for an HTMLElement/Window/Document: listeners fire
 * only when dispatched on the exact same fake, which is what proves test 1 (a keydown on
 * a page input never reaches the explore element's listener — there is no shared tree for
 * it to bubble through). */
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

  count(type: string): number {
    return this.listeners.get(type)?.size ?? 0;
  }
}

function keyEvent(key: string): KeyLikeEvent {
  return { key, preventDefault: vi.fn() };
}

describe("attachExploreKeyboard (C1, C2, W3-F8)", () => {
  it("test 1: a keydown dispatched on a different target never reaches this element's held keys", () => {
    const element = new FakeTarget();
    const pageInput = new FakeTarget();
    const win = new FakeTarget();
    const doc = new FakeTarget();
    const keyboard = attachExploreKeyboard(element, { onEscape: vi.fn() }, win, doc);

    pageInput.dispatch("keydown", keyEvent("w"));

    expect(keyboard.held.forward).toBe(false);
    keyboard.dispose();
  });

  it("moves the operator's held state only from the explore element", () => {
    const element = new FakeTarget();
    const win = new FakeTarget();
    const doc = new FakeTarget();
    const keyboard = attachExploreKeyboard(element, { onEscape: vi.fn() }, win, doc);

    element.dispatch("keydown", keyEvent("w"));
    expect(keyboard.held.forward).toBe(true);
    keyboard.dispose();
  });

  it("test 2: holding a key then blurring the window stops the avatar", () => {
    const element = new FakeTarget();
    const win = new FakeTarget();
    const doc = new FakeTarget();
    const keyboard = attachExploreKeyboard(element, { onEscape: vi.fn() }, win, doc);

    element.dispatch("keydown", keyEvent("w"));
    expect(keyboard.held.forward).toBe(true);
    win.dispatch("blur", {});
    expect(keyboard.held.forward).toBe(false);
    keyboard.dispose();
  });

  it("test 2: a visibilitychange while hidden also clears every held key", () => {
    const element = new FakeTarget();
    const win = new FakeTarget();
    const doc = new FakeTarget();
    const keyboard = attachExploreKeyboard(element, { onEscape: vi.fn() }, win, doc);

    element.dispatch("keydown", keyEvent("shift"));
    expect(keyboard.held.running).toBe(true);
    doc.hidden = true;
    doc.dispatch("visibilitychange", {});
    expect(keyboard.held.running).toBe(false);
    keyboard.dispose();
  });

  it("blurring the element itself also clears held keys", () => {
    const element = new FakeTarget();
    const win = new FakeTarget();
    const doc = new FakeTarget();
    const keyboard = attachExploreKeyboard(element, { onEscape: vi.fn() }, win, doc);

    element.dispatch("keydown", keyEvent("a"));
    element.dispatch("blur", {});
    expect(keyboard.held.left).toBe(false);
    keyboard.dispose();
  });

  it("calls onEscape and never sets a held direction for the Escape key", () => {
    const element = new FakeTarget();
    const win = new FakeTarget();
    const doc = new FakeTarget();
    const onEscape = vi.fn();
    const keyboard = attachExploreKeyboard(element, { onEscape }, win, doc);

    element.dispatch("keydown", keyEvent("Escape"));

    expect(onEscape).toHaveBeenCalledTimes(1);
    expect(Object.values(keyboard.held).every((v) => v === false)).toBe(true);
    keyboard.dispose();
  });

  it("test 3: a StrictMode-style mount, dispose, remount leaves exactly one listener set", () => {
    const element = new FakeTarget();
    const win = new FakeTarget();
    const doc = new FakeTarget();

    const first = attachExploreKeyboard(element, { onEscape: vi.fn() }, win, doc);
    first.dispose();
    const second = attachExploreKeyboard(element, { onEscape: vi.fn() }, win, doc);

    expect(element.count("keydown")).toBe(1);
    expect(element.count("keyup")).toBe(1);
    expect(element.count("blur")).toBe(1);
    expect(win.count("blur")).toBe(1);
    expect(doc.count("visibilitychange")).toBe(1);
    second.dispose();
    expect(element.count("keydown")).toBe(0);
  });

  it("dispose removes every listener it attached", () => {
    const element = new FakeTarget();
    const win = new FakeTarget();
    const doc = new FakeTarget();
    const keyboard = attachExploreKeyboard(element, { onEscape: vi.fn() }, win, doc);

    keyboard.dispose();

    expect(element.count("keydown")).toBe(0);
    expect(element.count("keyup")).toBe(0);
    expect(element.count("blur")).toBe(0);
    expect(win.count("blur")).toBe(0);
    expect(doc.count("visibilitychange")).toBe(0);
  });

  it("recognizes arrow keys as the same directions as WASD", () => {
    const element = new FakeTarget();
    const win = new FakeTarget();
    const doc = new FakeTarget();
    const keyboard = attachExploreKeyboard(element, { onEscape: vi.fn() }, win, doc);

    element.dispatch("keydown", keyEvent("ArrowUp"));
    expect(keyboard.held.forward).toBe(true);
    element.dispatch("keyup", keyEvent("ArrowUp"));
    expect(keyboard.held.forward).toBe(false);
    keyboard.dispose();
  });
});
