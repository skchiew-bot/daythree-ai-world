/** Coordinate mapping, hit-testing and the text alternative for the minimap (deliverable
 * 7, C8). Plain numbers, no canvas: the drawing itself lives in minimapDraw.ts so this
 * stays trivially testable. */
import type { Bounds } from "./footprints";
import { STREET_COUNT, streetZ } from "./town";

export interface CanvasPoint {
  x: number;
  y: number;
}

export interface WorldPoint {
  x: number;
  z: number;
}

function scaleFor(bounds: Bounds, size: number): { scale: number; offsetX: number; offsetY: number } {
  const spanX = bounds.maxX - bounds.minX || 1;
  const spanZ = bounds.maxZ - bounds.minZ || 1;
  const scale = Math.min(size / spanX, size / spanZ);
  return { scale, offsetX: (size - spanX * scale) / 2, offsetY: (size - spanZ * scale) / 2 };
}

export function worldToCanvas(x: number, z: number, bounds: Bounds, size: number): CanvasPoint {
  const { scale, offsetX, offsetY } = scaleFor(bounds, size);
  return { x: offsetX + (x - bounds.minX) * scale, y: offsetY + (z - bounds.minZ) * scale };
}

export function canvasToWorld(px: number, py: number, bounds: Bounds, size: number): WorldPoint {
  const { scale, offsetX, offsetY } = scaleFor(bounds, size);
  return { x: bounds.minX + (px - offsetX) / scale, z: bounds.minZ + (py - offsetY) / scale };
}

/** The index of the closest dot within `maxDistPx`, for the hover tooltip and for
 * distinguishing "clicked a twin" from "clicked empty ground" (D21). */
export function nearestDot(px: number, py: number, dots: readonly CanvasPoint[], maxDistPx = 8): number | null {
  let best: number | null = null;
  let bestDist = maxDistPx;
  for (let i = 0; i < dots.length; i++) {
    const dist = Math.hypot(px - dots[i].x, py - dots[i].y);
    if (dist <= bestDist) {
      bestDist = dist;
      best = i;
    }
  }
  return best;
}

/** A plain, non-sensitive label for the operator's current street (C8): the street whose
 * spine is closest to the operator's z. Never a project code or twin name. */
export function nearestStreetLabel(z: number): string {
  let best = 0;
  let bestDist = Infinity;
  for (let i = 0; i < STREET_COUNT; i++) {
    const dist = Math.abs(z - streetZ(i));
    if (dist < bestDist) {
      bestDist = dist;
      best = i;
    }
  }
  return `Street ${best + 1}`;
}

export interface MinimapTextInfo {
  buildingCodes: readonly string[];
  twinCount: number;
  street: string;
}

/** The text alternative (C8): building codes, the twin count and the operator's current
 * street — nothing per-twin, nothing from `name`. */
export function minimapSummary(info: MinimapTextInfo): string {
  const codes = info.buildingCodes.length > 0 ? info.buildingCodes.join(", ") : "none yet";
  return `Minimap. Buildings: ${codes}. Twins in town: ${info.twinCount}. You are on ${info.street}.`;
}
