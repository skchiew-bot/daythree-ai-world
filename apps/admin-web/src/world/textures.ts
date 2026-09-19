import * as THREE from "three";

import { mulberry32 } from "./rng";

/** Procedural textures drawn onto canvases at start-up: no fetched images, no CDN.
 * Seeded, so the building looks the same on every load. Tiles are 1 to 2 metres wide. */
const SIZE = 256;

function canvasTexture(draw: (ctx: CanvasRenderingContext2D, rand: () => number) => void, seed: number): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = SIZE;
  canvas.height = SIZE;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("2D canvas unavailable");
  draw(ctx, mulberry32(seed));

  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

function speckle(ctx: CanvasRenderingContext2D, rand: () => number, count: number, alpha: number): void {
  for (let i = 0; i < count; i++) {
    const shade = rand() > 0.5 ? 255 : 0;
    ctx.fillStyle = `rgba(${shade},${shade},${shade},${alpha * rand()})`;
    ctx.fillRect(rand() * SIZE, rand() * SIZE, 1 + rand() * 2, 1 + rand() * 2);
  }
}

/** Warm oak planks running across the tile. */
export function woodTexture(): THREE.CanvasTexture {
  return canvasTexture((ctx, rand) => {
    const planks = 4;
    const height = SIZE / planks;
    for (let row = 0; row < planks; row++) {
      const light = 62 + rand() * 10;
      ctx.fillStyle = `hsl(${30 + rand() * 6} 45% ${light}%)`;
      ctx.fillRect(0, row * height, SIZE, height);
      for (let g = 0; g < 14; g++) {
        ctx.strokeStyle = `rgba(90,55,25,${0.05 + rand() * 0.1})`;
        ctx.beginPath();
        const y = row * height + rand() * height;
        ctx.moveTo(0, y);
        ctx.bezierCurveTo(SIZE * 0.3, y + rand() * 4 - 2, SIZE * 0.7, y + rand() * 4 - 2, SIZE, y);
        ctx.stroke();
      }
      ctx.fillStyle = "rgba(60,35,15,0.55)";
      ctx.fillRect(0, row * height, SIZE, 2);
      const joint = rand() * SIZE;
      ctx.fillRect(joint, row * height, 2, height);
    }
  }, 11);
}

/** Soft plaster with faint mottling. Tinted per room through the material colour. */
export function plasterTexture(): THREE.CanvasTexture {
  return canvasTexture((ctx, rand) => {
    ctx.fillStyle = "#f4f1ea";
    ctx.fillRect(0, 0, SIZE, SIZE);
    for (let i = 0; i < 90; i++) {
      const r = 12 + rand() * 40;
      const gradient = ctx.createRadialGradient(rand() * SIZE, rand() * SIZE, 0, rand() * SIZE, rand() * SIZE, r);
      gradient.addColorStop(0, `rgba(120,110,95,${0.03 * rand()})`);
      gradient.addColorStop(1, "rgba(120,110,95,0)");
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, SIZE, SIZE);
    }
    speckle(ctx, rand, 600, 0.08);
  }, 23);
}

/** Large stone tiles with grout lines, for the corridor. */
export function tileTexture(): THREE.CanvasTexture {
  return canvasTexture((ctx, rand) => {
    const cells = 2;
    const cell = SIZE / cells;
    for (let x = 0; x < cells; x++) {
      for (let y = 0; y < cells; y++) {
        const tone = 208 + rand() * 22;
        ctx.fillStyle = `rgb(${tone},${tone - 4},${tone - 12})`;
        ctx.fillRect(x * cell, y * cell, cell, cell);
      }
    }
    ctx.fillStyle = "rgba(90,90,90,0.55)";
    for (let i = 0; i < cells; i++) {
      ctx.fillRect(i * cell, 0, 3, SIZE);
      ctx.fillRect(0, i * cell, SIZE, 3);
    }
    speckle(ctx, rand, 500, 0.12);
  }, 37);
}

/** Dark pavers for the plaza around the building. */
export function paverTexture(): THREE.CanvasTexture {
  return canvasTexture((ctx, rand) => {
    ctx.fillStyle = "#26324a";
    ctx.fillRect(0, 0, SIZE, SIZE);
    const cells = 4;
    const cell = SIZE / cells;
    for (let x = 0; x < cells; x++) {
      for (let y = 0; y < cells; y++) {
        ctx.fillStyle = `rgba(255,255,255,${0.02 + rand() * 0.05})`;
        ctx.fillRect(x * cell + 2, y * cell + 2, cell - 4, cell - 4);
      }
    }
    speckle(ctx, rand, 300, 0.1);
  }, 41);
}
