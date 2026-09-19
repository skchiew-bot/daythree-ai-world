import * as THREE from "three";

const CANVAS_W = 256;
const CANVAS_H = 64;
const FONT_FAMILY = "system-ui, sans-serif";
const MAX_FONT_PX = 40;
const MIN_FONT_PX = 14;
const PADDING_PX = 12;

/** Draws `text` (a project's code, or "HALL") on a canvas texture. This is the only text
 * the scene ever renders (ADR-014 decision 5, D13): a project's name is never passed here.
 * Drawn procedurally, so no font or image is fetched. */
function drawSignTexture(text: string): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = CANVAS_W;
  canvas.height = CANVAS_H;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.fillStyle = "#1f2937";
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H);
    ctx.strokeStyle = "#f8fafc";
    ctx.lineWidth = 3;
    ctx.strokeRect(3, 3, CANVAS_W - 6, CANVAS_H - 6);

    let size = MAX_FONT_PX;
    ctx.font = `700 ${size}px ${FONT_FAMILY}`;
    while (size > MIN_FONT_PX && ctx.measureText(text).width > CANVAS_W - PADDING_PX * 2) {
      size -= 2;
      ctx.font = `700 ${size}px ${FONT_FAMILY}`;
    }
    ctx.fillStyle = "#f8fafc";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, CANVAS_W / 2, CANVAS_H / 2 + 2);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

export interface SignMesh {
  mesh: THREE.Mesh;
  /** Frees this sign's geometry, material and texture. */
  dispose: () => void;
}

/** A small facade sign facing +z, centred at (x, y, z). */
export function buildSign(text: string, width: number, x: number, y: number, z: number): SignMesh {
  const texture = drawSignTexture(text);
  const material = new THREE.MeshBasicMaterial({ map: texture, toneMapped: false });
  const geometry = new THREE.PlaneGeometry(width, width * (CANVAS_H / CANVAS_W));
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.set(x, y, z);
  return {
    mesh,
    dispose: () => {
      geometry.dispose();
      material.dispose();
      texture.dispose();
    },
  };
}
