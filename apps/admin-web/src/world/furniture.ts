import type { GeometryBatcher } from "./batch";
import { floorY, LOBBY_SPOT_XS, ROOM_DEPTH, roomCenterX, roomKey } from "./layout";
import { ACCENT_COUNT } from "./materials";
import { mulberry32, hashString } from "./rng";

/** Colour scheme of a room; neighbours on a floor and rooms one floor apart differ. */
export function accentFor(floor: number, roomIndex: number): number {
  return (roomIndex - 1 + (floor - 1) * 2) % ACCENT_COUNT;
}

interface Origin {
  b: GeometryBatcher;
  cx: number;
  y: number;
}

function addBed(o: Origin, accent: number): void {
  const { b, cx, y } = o;
  const x = cx - 0.72;
  b.box("bedFrame", 0.92, 0.14, 1.42, x, y + 0.07, -0.3);
  b.box("bedFrame", 0.94, 0.55, 0.06, x, y + 0.28, -1.05);
  b.box("mattress", 0.86, 0.12, 1.34, x, y + 0.2, -0.3);
  b.box(`blanket${accent}`, 0.88, 0.05, 0.82, x, y + 0.28, 0.0);
  b.box("pillow", 0.5, 0.09, 0.24, x, y + 0.3, -0.83);
}

function addDesk(o: Origin): void {
  const { b, cx, y } = o;
  const x = cx + 0.92;
  b.box("deskWood", 0.5, 0.05, 0.95, x, y + 0.44, 0.05);
  for (const [lx, lz] of [[-0.2, -0.4], [-0.2, 0.5], [0.2, -0.4], [0.2, 0.5]]) {
    b.box("metal", 0.04, 0.42, 0.04, x + lx, y + 0.21, lz);
  }
  b.box("metal", 0.05, 0.1, 0.12, x + 0.08, y + 0.52, 0.05);
  b.box("monitorBody", 0.03, 0.26, 0.42, x + 0.11, y + 0.72, 0.05);
  b.box("screen", 0.006, 0.22, 0.38, x + 0.094, y + 0.72, 0.05);
  b.box("monitorBody", 0.16, 0.015, 0.32, x - 0.12, y + 0.47, 0.05);
  b.cylinder("metal", 0.05, 0.05, 0.02, x + 0.12, y + 0.47, -0.32);
  b.cylinder("metal", 0.01, 0.01, 0.3, x + 0.12, y + 0.62, -0.32, 6);
  b.sphere("lampGlow", 0.06, x + 0.06, y + 0.79, -0.32);
}

function addChair(o: Origin): void {
  const { b, cx, y } = o;
  const x = cx + 0.5;
  b.box("chairFabric", 0.34, 0.05, 0.34, x, y + 0.3, 0.05);
  b.box("chairFabric", 0.04, 0.36, 0.32, x - 0.18, y + 0.5, 0.05);
  b.cylinder("metal", 0.025, 0.025, 0.28, x, y + 0.14, 0.05, 8);
  b.box("metal", 0.32, 0.02, 0.04, x, y + 0.01, 0.05);
  b.box("metal", 0.04, 0.02, 0.32, x, y + 0.01, 0.05);
}

function addShelf(o: Origin, rand: () => number): void {
  const { b, cx, y } = o;
  const z = -0.94;
  b.box("deskWood", 0.7, 1.0, 0.02, cx, y + 0.5, -1.07);
  for (const side of [-0.335, 0.335]) b.box("deskWood", 0.03, 1.0, 0.26, cx + side, y + 0.5, z);
  for (const level of [0.03, 0.4, 0.7, 1.0]) b.box("deskWood", 0.7, 0.03, 0.26, cx, y + level, z);
  const bookMaterials = ["bookA", "bookB", "bookC"];
  for (const level of [0.7, 0.4]) {
    let x = cx - 0.3;
    for (let i = 0; i < 6 && x < cx + 0.3; i++) {
      const height = 0.14 + rand() * 0.1;
      const width = 0.045 + rand() * 0.02;
      b.box(bookMaterials[Math.floor(rand() * 3)], width, height, 0.16, x, y + level + 0.015 + height / 2, z);
      x += width + 0.012;
    }
  }
}

function addWallArt(o: Origin): void {
  const { b, cx, y } = o;
  b.box("trim", 0.5, 0.34, 0.02, cx - 0.62, y + 1.15, -1.09);
  b.box("artCanvas", 0.42, 0.26, 0.02, cx - 0.62, y + 1.15, -1.08);
  b.box("trim", 0.56, 0.56, 0.02, cx + 0.78, y + 1.15, -1.095);
  b.box("windowGlass", 0.5, 0.5, 0.02, cx + 0.78, y + 1.15, -1.085);
}

function addPlant(b: GeometryBatcher, x: number, y: number, z: number, scale: number): void {
  b.cylinder("pot", 0.11 * scale, 0.08 * scale, 0.22 * scale, x, y + 0.11 * scale, z);
  b.sphere("foliage", 0.16 * scale, x, y + 0.36 * scale, z);
  b.sphere("foliage2", 0.12 * scale, x + 0.07 * scale, y + 0.52 * scale, z - 0.03 * scale);
  b.sphere("foliage2", 0.11 * scale, x - 0.07 * scale, y + 0.47 * scale, z + 0.05 * scale);
}

function addFloorLamp(b: GeometryBatcher, x: number, y: number, z: number): void {
  b.cylinder("metal", 0.08, 0.08, 0.02, x, y + 0.01, z);
  b.cylinder("metal", 0.015, 0.015, 1.05, x, y + 0.525, z, 6);
  b.cylinder("lampGlow", 0.1, 0.14, 0.2, x, y + 1.1, z);
}

/** A room is built from primitives in room-local terms: x from the room's centre, z from
 * the middle of its depth. The back wall is at z = -1.1, the open front at +1.1, the desk
 * against the right wall, the bed against the left, and a clear lane down the middle so
 * avatars never clip furniture. */
export function addRoomFurniture(b: GeometryBatcher, floor: number, roomIndex: number): void {
  const o: Origin = { b, cx: roomCenterX(roomIndex), y: floorY(floor) };
  const accent = accentFor(floor, roomIndex);
  const rand = mulberry32(hashString(roomKey(floor, roomIndex)));

  b.box(`rug${accent}`, 1.3, 0.012, 0.95, o.cx, o.y + 0.006, 0.25);
  addBed(o, accent);
  addDesk(o);
  addChair(o);
  addShelf(o, rand);
  addWallArt(o);
  addPlant(b, o.cx - 0.95, o.y, ROOM_DEPTH / 2 - 0.25, 1);
  addFloorLamp(b, o.cx + 0.95, o.y, ROOM_DEPTH / 2 - 0.25);
}

/** Lobby dressing in the middle of the corridor: a rug under the standing places, a
 * bench along the rail, plants and lamps. Nothing stands on the walking lane. */
export function addLobbyFurniture(b: GeometryBatcher, floor: number): void {
  const y = floorY(floor);
  const spotSpan = LOBBY_SPOT_XS[LOBBY_SPOT_XS.length - 1] - LOBBY_SPOT_XS[0];
  b.box("lobbyRug", spotSpan + 1.2, 0.012, 0.72, 0, y + 0.006, ROOM_DEPTH / 2 + 0.55);
  b.box("bench", 1.9, 0.26, 0.2, 0, y + 0.13, ROOM_DEPTH / 2 + 0.87);
  b.box("bench", 1.9, 0.26, 0.05, 0, y + 0.4, ROOM_DEPTH / 2 + 0.96);
  for (const side of [-1, 1]) {
    addPlant(b, side * 2.15, y, ROOM_DEPTH / 2 + 0.85, 1.5);
    addFloorLamp(b, side * 1.7, y, ROOM_DEPTH / 2 + 0.9);
  }
}
