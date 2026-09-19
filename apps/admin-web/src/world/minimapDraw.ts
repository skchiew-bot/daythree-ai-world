/** Draws the minimap (deliverable 7): roads and buildings as geometry with no labels, the
 * operator as an arrow with heading, twins as dots. Takes a small drawing-context
 * interface rather than `CanvasRenderingContext2D` itself, so a test can pass a recording
 * fake without a real canvas. The static layer (roads, buildings) is meant to be drawn
 * once per project-set signature onto an offscreen canvas; the dynamic layer (operator,
 * twins) redraws at C6's 10 Hz cap. */
import type { Footprint } from "./footprints";
import { arrowTip, headingVector, worldToCanvas } from "./minimapMath";
import type { Bounds } from "./footprints";
import type { RoadGraph } from "./town";

export interface DrawCtx {
  clearRect(x: number, y: number, w: number, h: number): void;
  fillRect(x: number, y: number, w: number, h: number): void;
  beginPath(): void;
  moveTo(x: number, y: number): void;
  lineTo(x: number, y: number): void;
  closePath(): void;
  stroke(): void;
  fill(): void;
  arc(x: number, y: number, r: number, startAngle: number, endAngle: number): void;
  fillStyle: string | CanvasGradient | CanvasPattern;
  strokeStyle: string | CanvasGradient | CanvasPattern;
  lineWidth: number;
}

const ROAD_COLOR = "#c9c2b3";
const BUILDING_COLOR = "#8a7f6a";
const BACKGROUND_COLOR = "#e9e4d8";
const OPERATOR_COLOR = "#1d4ed8";
const TWIN_COLOR = "#16a34a";
const DOT_RADIUS_PX = 2.4;
const ARROW_SIZE_PX = 5;

/** Draws roads (once per edge, since the graph stores both directions) and building
 * footprints. No text is ever drawn here (roads/buildings carry no labels, D21). */
export function drawStaticLayer(ctx: DrawCtx, size: number, bounds: Bounds, roads: RoadGraph, buildings: readonly Footprint[]): void {
  ctx.fillStyle = BACKGROUND_COLOR;
  ctx.clearRect(0, 0, size, size);
  ctx.fillRect(0, 0, size, size);

  ctx.strokeStyle = ROAD_COLOR;
  ctx.lineWidth = 2;
  const drawn = new Set<string>();
  for (const [from, neighbors] of roads.edges) {
    const a = roads.nodes.get(from);
    if (!a) continue;
    for (const { to } of neighbors) {
      const edgeKey = from < to ? `${from}|${to}` : `${to}|${from}`;
      if (drawn.has(edgeKey)) continue;
      drawn.add(edgeKey);
      const b = roads.nodes.get(to);
      if (!b) continue;
      const pa = worldToCanvas(a.x, a.z, bounds, size);
      const pb = worldToCanvas(b.x, b.z, bounds, size);
      ctx.beginPath();
      ctx.moveTo(pa.x, pa.y);
      ctx.lineTo(pb.x, pb.y);
      ctx.stroke();
    }
  }

  ctx.fillStyle = BUILDING_COLOR;
  for (const fp of buildings) {
    const topLeft = worldToCanvas(fp.minX, fp.minZ, bounds, size);
    const bottomRight = worldToCanvas(fp.maxX, fp.maxZ, bounds, size);
    ctx.fillRect(topLeft.x, topLeft.y, bottomRight.x - topLeft.x, bottomRight.y - topLeft.y);
  }
}

/** Draws the twins (plain dots) and the operator (an arrow pointing at its heading). */
export function drawDynamicLayer(
  ctx: DrawCtx,
  size: number,
  bounds: Bounds,
  operator: { x: number; z: number; heading: number },
  twins: readonly { x: number; z: number }[],
): void {
  ctx.fillStyle = TWIN_COLOR;
  for (const twin of twins) {
    const p = worldToCanvas(twin.x, twin.z, bounds, size);
    ctx.beginPath();
    ctx.arc(p.x, p.y, DOT_RADIUS_PX, 0, Math.PI * 2);
    ctx.fill();
  }

  const op = worldToCanvas(operator.x, operator.z, bounds, size);
  const tip = arrowTip(op, operator.heading, ARROW_SIZE_PX);
  // The two trailing corners: back along the heading, then out to either side of it —
  // built from the same `headingVector` as the tip, so the two can never disagree again.
  const dir = headingVector(operator.heading);
  const backX = op.x - dir.x * ARROW_SIZE_PX * 0.7;
  const backY = op.y - dir.y * ARROW_SIZE_PX * 0.7;
  const sideX = dir.y * ARROW_SIZE_PX * 0.6;
  const sideY = -dir.x * ARROW_SIZE_PX * 0.6;

  ctx.fillStyle = OPERATOR_COLOR;
  ctx.beginPath();
  ctx.moveTo(tip.x, tip.y);
  ctx.lineTo(backX + sideX, backY + sideY);
  ctx.lineTo(backX - sideX, backY - sideY);
  ctx.closePath();
  ctx.fill();
}
