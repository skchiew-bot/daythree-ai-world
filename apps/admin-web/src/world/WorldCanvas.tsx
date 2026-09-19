import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from "react";

import type { ExploreMode, FollowInfo, ProximityInfo } from "./explorer";
import type { MinimapDotInfo } from "./Minimap";
import { Minimap } from "./Minimap";
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
  followAgent: (agentId: string) => void;
}

const EXPLORE_LABEL = "Town explorer: WASD or arrows to walk, Shift to run, drag to turn, Esc to return to overview";

/** Hosts the 3D scene, plus the W3 explore layer: a keyboard-and-drag-scoped overlay
 * (separate from the `role="img"` canvas, W3-F5), mode buttons, a proximity card, a
 * follow panel and the minimap. The scene is created once and reads the latest props
 * through a ref on every frame, so the 3-second poll re-renders React without rebuilding
 * WebGL. */
export const WorldCanvas = forwardRef<WorldCanvasApi, WorldCanvasProps>(function WorldCanvas(
  { label, describedBy, onFocusChange, ...inputs },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null);
  const exploreRef = useRef<HTMLDivElement>(null);
  const minimapCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const latest = useRef<WorldInputs>(inputs);
  const handle = useRef<WorldHandle | null>(null);
  const focusCallback = useRef(onFocusChange);

  const [mode, setModeState] = useState<ExploreMode>("fly");
  const [proximity, setProximity] = useState<ProximityInfo | null>(null);
  const [follow, setFollow] = useState<FollowInfo | null>(null);
  const [minimapText, setMinimapText] = useState("Minimap.");
  const [minimapDots, setMinimapDots] = useState<readonly MinimapDotInfo[]>([]);

  // Written after commit, not during render, so a discarded concurrent render can never
  // leak its props into the scene. Layout effects run before the scene effect below.
  useLayoutEffect(() => {
    latest.current = inputs;
    focusCallback.current = onFocusChange;
  });

  useImperativeHandle(
    ref,
    () => ({
      focus: (key) => handle.current?.focus(key),
      followAgent: (agentId) => handle.current?.followAgent(agentId),
    }),
    [],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !exploreRef.current) return;
    const world = runWorld(container, () => latest.current, undefined, {
      onFocusChange: (key) => focusCallback.current?.(key),
      onModeChange: setModeState,
      onProximityChange: setProximity,
      onFollowChange: setFollow,
      onMinimapText: setMinimapText,
      onMinimapDots: setMinimapDots,
      exploreElement: exploreRef.current,
      minimapCanvas: minimapCanvasRef.current ?? undefined,
    });
    handle.current = world;
    return () => {
      handle.current = null;
      world.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div style={{ position: "relative", overflow: "hidden", width: "100%", height: "75vh", minHeight: 360 }}>
      <div ref={containerRef} role="img" aria-label={label} aria-describedby={describedBy} style={{ position: "absolute", inset: 0 }} />

      {/* The explore layer (W3-F5): its own focusable element, outside the role="img"
          node. Pointer events pass through to the canvas in fly mode (OrbitControls and
          building clicks own the canvas there) and are captured here in walk/follow. */}
      <div
        ref={exploreRef}
        tabIndex={0}
        role="application"
        aria-label={EXPLORE_LABEL}
        style={{ position: "absolute", inset: 0, pointerEvents: mode === "fly" ? "none" : "auto", touchAction: "none" }}
      />

      <div style={{ position: "absolute", top: "0.75rem", left: "0.75rem", display: "flex", gap: "0.4rem", zIndex: 2 }}>
        <button type="button" aria-pressed={mode === "fly"} onClick={() => handle.current?.setMode("fly")}>
          Fly
        </button>
        <button type="button" aria-pressed={mode === "walk"} onClick={() => handle.current?.setMode("walk")}>
          Walk
        </button>
        {mode === "follow" && (
          <button type="button" onClick={() => handle.current?.setMode("walk")}>
            Stop following
          </button>
        )}
      </div>

      {mode === "walk" && proximity && (
        <div className="card" style={proximityCardStyle} aria-live="polite">
          <strong>{proximity.code}</strong> <span className={`badge status-${proximity.status}`}>{proximity.status}</span>
          {proximity.twins.length > 0 && (
            <ul style={{ margin: "0.35rem 0 0", paddingLeft: "1rem" }}>
              {proximity.twins.map((twin, i) => (
                <li key={i}>
                  {twin.display_name} — {twin.activity}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {mode === "follow" && follow && (
        <div className="card" style={proximityCardStyle} aria-live="polite">
          <strong>{follow.display_name}</strong> — {follow.activity}
          <div style={{ color: "var(--text-muted)", fontSize: "0.85em" }}>At {follow.place}</div>
        </div>
      )}

      <Minimap
        onCanvasReady={(canvas) => {
          minimapCanvasRef.current = canvas;
        }}
        dots={minimapDots}
        text={minimapText}
        onPick={(x, z) => handle.current?.teleport(x, z)}
      />
    </div>
  );
});

const proximityCardStyle: React.CSSProperties = {
  position: "absolute",
  bottom: "0.75rem",
  left: "0.75rem",
  maxWidth: "16rem",
  zIndex: 2,
};
