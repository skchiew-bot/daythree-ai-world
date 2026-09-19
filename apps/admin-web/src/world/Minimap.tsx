import { useEffect, useRef, useState } from "react";

import { townBounds } from "./footprints";
import { canvasToWorld, nearestDot } from "./minimapMath";

export const MINIMAP_SIZE_PX = 160;

export interface MinimapDotInfo {
  x: number;
  y: number;
  display_name: string;
  activity: string;
}

interface MinimapProps {
  /** Fired once with the canvas element so the parent can hand it to `runWorld`, which
   * owns all drawing (deliverable 7: the static layer is drawn once per signature, the
   * dynamic layer at 10 Hz or less). Minimap itself never draws. */
  onCanvasReady: (canvas: HTMLCanvasElement) => void;
  dots: readonly MinimapDotInfo[];
  text: string;
  /** Click teleports in walk mode, focuses a building in fly mode (deliverable 7). */
  onPick: (x: number, z: number) => void;
}

/** The minimap corner widget: the canvas `runWorld` draws onto, a hover tooltip limited
 * to a twin's `display_name` and `activity` (D21), and the text alternative (C8). The
 * canvas itself sits outside the `role="img"` 3D view (W3-F5) — it is its own small
 * interactive control, not part of the keyboard-scoped explore element. */
export function Minimap({ onCanvasReady, dots, text, onPick }: MinimapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hover, setHover] = useState<{ x: number; y: number; label: string } | null>(null);

  useEffect(() => {
    if (canvasRef.current) onCanvasReady(canvasRef.current);
    // Only ever fires once: the canvas element itself never changes identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleMove = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const mx = event.clientX - rect.left;
    const my = event.clientY - rect.top;
    const index = nearestDot(mx, my, dots);
    if (index === null) {
      setHover(null);
      return;
    }
    const dot = dots[index];
    setHover({ x: mx, y: my, label: `${dot.display_name} — ${dot.activity}` });
  };

  const handleClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const point = canvasToWorld(event.clientX - rect.left, event.clientY - rect.top, townBounds(), MINIMAP_SIZE_PX);
    onPick(point.x, point.z);
  };

  return (
    <div style={{ position: "absolute", top: "0.75rem", right: "0.75rem", zIndex: 2 }}>
      <canvas
        ref={canvasRef}
        width={MINIMAP_SIZE_PX}
        height={MINIMAP_SIZE_PX}
        role="img"
        aria-label={text}
        onMouseMove={handleMove}
        onMouseLeave={() => setHover(null)}
        onClick={handleClick}
        style={{ borderRadius: "0.5rem", boxShadow: "0 2px 8px rgba(0,0,0,0.35)", cursor: "pointer", display: "block" }}
      />
      {hover && (
        <div
          role="tooltip"
          style={{
            position: "absolute",
            left: hover.x + 8,
            top: hover.y + 8,
            background: "rgba(15,23,42,0.9)",
            color: "#fff",
            padding: "0.15rem 0.4rem",
            borderRadius: "0.25rem",
            fontSize: "0.75rem",
            pointerEvents: "none",
            whiteSpace: "nowrap",
          }}
        >
          {hover.label}
        </div>
      )}
      <p className="sr-only" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>
        {text}
      </p>
    </div>
  );
}
