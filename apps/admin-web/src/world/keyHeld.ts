/** The only keyboard listener in W3 (C1, C2, W3-F8): attached to the explore element
 * itself, never `window` or `document`. Held keys are cleared on blur (the element losing
 * focus, or the browser window losing it) and on `visibilitychange`, so a key stuck down
 * when the user alt-tabs away never keeps the operator walking. `dispose` removes every
 * listener this attached, so a StrictMode double-mount leaves exactly one active set. */
export interface KeyTarget {
  addEventListener(type: string, listener: (event: KeyLikeEvent) => void): void;
  removeEventListener(type: string, listener: (event: KeyLikeEvent) => void): void;
}

interface BareTarget {
  addEventListener(type: string, listener: () => void): void;
  removeEventListener(type: string, listener: () => void): void;
}

export interface KeyLikeEvent {
  key: string;
  repeat?: boolean;
  preventDefault(): void;
}

export type WalkKey = "forward" | "backward" | "left" | "right" | "running";

const KEY_MAP: Record<string, WalkKey> = {
  w: "forward",
  arrowup: "forward",
  s: "backward",
  arrowdown: "backward",
  a: "left",
  arrowleft: "left",
  d: "right",
  arrowright: "right",
  shift: "running",
};

export interface ExploreKeyboardHandlers {
  onEscape: () => void;
}

export interface ExploreKeyboard {
  readonly held: Readonly<Record<WalkKey, boolean>>;
  dispose: () => void;
}

function emptyHeld(): Record<WalkKey, boolean> {
  return { forward: false, backward: false, left: false, right: false, running: false };
}

/** `win`/`doc` default to the real globals; tests pass fakes so no jsdom is needed. */
export function attachExploreKeyboard(
  element: KeyTarget,
  handlers: ExploreKeyboardHandlers,
  win: BareTarget = window,
  doc: BareTarget & { hidden?: boolean } = document,
): ExploreKeyboard {
  const held = emptyHeld();

  const clearAll = (): void => {
    held.forward = false;
    held.backward = false;
    held.left = false;
    held.right = false;
    held.running = false;
  };

  const onKeyDown = (event: KeyLikeEvent): void => {
    const key = event.key.toLowerCase();
    if (key === "escape") {
      event.preventDefault();
      handlers.onEscape();
      return;
    }
    const mapped = KEY_MAP[key];
    if (!mapped) return;
    event.preventDefault();
    held[mapped] = true;
  };

  const onKeyUp = (event: KeyLikeEvent): void => {
    const mapped = KEY_MAP[event.key.toLowerCase()];
    if (!mapped) return;
    event.preventDefault();
    held[mapped] = false;
  };

  const onVisibilityChange = (): void => {
    if (doc.hidden) clearAll();
  };

  element.addEventListener("keydown", onKeyDown);
  element.addEventListener("keyup", onKeyUp);
  element.addEventListener("blur", clearAll);
  win.addEventListener("blur", clearAll);
  doc.addEventListener("visibilitychange", onVisibilityChange);

  return {
    held,
    dispose: () => {
      clearAll();
      element.removeEventListener("keydown", onKeyDown);
      element.removeEventListener("keyup", onKeyUp);
      element.removeEventListener("blur", clearAll);
      win.removeEventListener("blur", clearAll);
      doc.removeEventListener("visibilitychange", onVisibilityChange);
    },
  };
}
