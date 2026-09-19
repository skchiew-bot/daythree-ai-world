import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef } from "react";

import { runWorld, type WorldHandle, type WorldInputs } from "./runWorld";

interface WorldCanvasProps extends WorldInputs {
  /** Text alternative for the canvas; built from counts only, never from free text. */
  label: string;
  describedBy?: string;
  /** Called when a click on a building changes the focus (project id, "hall" or null). */
  onFocusChange?: (key: string | null) => void;
}

/** What a parent can ask of the running scene. */
export interface WorldCanvasApi {
  focus: (key: string | null) => void;
}

/** Hosts the 3D scene. The scene is created once and reads the latest props through a
 * ref on every frame, so the 3-second poll re-renders React without rebuilding WebGL. */
export const WorldCanvas = forwardRef<WorldCanvasApi, WorldCanvasProps>(function WorldCanvas(
  { label, describedBy, onFocusChange, ...inputs },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const latest = useRef<WorldInputs>(inputs);
  const handle = useRef<WorldHandle | null>(null);
  const focusCallback = useRef(onFocusChange);
  // Written after commit, not during render, so a discarded concurrent render can never
  // leak its props into the scene. Layout effects run before the scene effect below.
  useLayoutEffect(() => {
    latest.current = inputs;
    focusCallback.current = onFocusChange;
  });

  useImperativeHandle(ref, () => ({ focus: (key) => handle.current?.focus(key) }), []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const world = runWorld(container, () => latest.current, undefined, {
      onFocusChange: (key) => focusCallback.current?.(key),
    });
    handle.current = world;
    return () => {
      handle.current = null;
      world.dispose();
    };
  }, []);

  return (
    <div
      ref={containerRef}
      role="img"
      aria-label={label}
      aria-describedby={describedBy}
      style={{ position: "relative", overflow: "hidden", width: "100%", height: "75vh", minHeight: 360 }}
    />
  );
});
