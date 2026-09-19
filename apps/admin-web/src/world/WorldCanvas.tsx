import { useEffect, useLayoutEffect, useRef } from "react";

import { runWorld, type WorldInputs } from "./runWorld";

interface WorldCanvasProps extends WorldInputs {
  /** Text alternative for the canvas; built from counts only, never from free text. */
  label: string;
  describedBy?: string;
}

/** Hosts the 3D scene. The scene is created once and reads the latest props through a
 * ref on every frame, so the 3-second poll re-renders React without rebuilding WebGL. */
export function WorldCanvas({ label, describedBy, ...inputs }: WorldCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const latest = useRef<WorldInputs>(inputs);
  // Written after commit, not during render, so a discarded concurrent render can never
  // leak its props into the scene. Layout effects run before the scene effect below.
  useLayoutEffect(() => {
    latest.current = inputs;
  });

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    return runWorld(container, () => latest.current);
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
}
