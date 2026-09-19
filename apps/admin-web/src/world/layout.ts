/** Building geometry as plain numbers (no three.js), so schedules and routes stay
 * unit-testable. Every room anchor is a pure function of (floor, roomIndex), never of
 * array order, so registering an unrelated agent never moves anyone else's room (ADR-009).
 *
 * Plan view, per floor (camera looks from +z):
 *   z = -1.1 .. 1.1   the four rooms (back wall at z = -1.1)
 *   z =  1.1 .. 2.1   the corridor gallery, with the lobby in its middle */
export interface Vec2 {
  x: number;
  z: number;
}

export interface Vec3 extends Vec2 {
  y: number;
}

export const ROOMS_PER_FLOOR = 4;
export const ROOM_WIDTH = 2.4;
export const ROOM_DEPTH = 2.2;
export const FLOOR_HEIGHT = 1.9;
export const BUILDING_WIDTH = ROOMS_PER_FLOOR * ROOM_WIDTH;

export const CORRIDOR_DEPTH = 1.0;
export const CORRIDOR_LANE_Z = ROOM_DEPTH / 2 + 0.35;
export const CORRIDOR_END_X = BUILDING_WIDTH / 2 - 0.45;
export const LOBBY_SPOT_Z = ROOM_DEPTH / 2 + 0.55;
/** Standing places in the lobby. Agents on one floor take different places, see idleSchedule. */
export const LOBBY_SPOT_XS: readonly number[] = [-1.2, -0.4, 0.4, 1.2];

export interface RoomAnchors {
  center: Vec3;
  /** Where an idle agent stands inside its room. */
  idle: Vec3;
  /** The chair: where an assigned or working agent sits. */
  desk: Vec3;
  /** Just inside the room's open front. */
  door: Vec3;
}

/** Keeps a room index inside 1..ROOMS_PER_FLOOR. The API never sends anything else, but a
 * bad value must not turn into NaN positions or an undefined lobby spot. */
export function clampRoomIndex(roomIndex: number): number {
  if (!Number.isFinite(roomIndex)) return 1;
  return Math.min(Math.max(Math.round(roomIndex), 1), ROOMS_PER_FLOOR);
}

export function roomCenterX(roomIndex: number): number {
  const startX = -BUILDING_WIDTH / 2 + ROOM_WIDTH / 2;
  return startX + (roomIndex - 1) * ROOM_WIDTH;
}

export function floorY(floor: number): number {
  return (floor - 1) * FLOOR_HEIGHT;
}

export function roomAnchors(floor: number, roomIndex: number): RoomAnchors {
  const x = roomCenterX(roomIndex);
  const y = floorY(floor);

  return {
    center: { x, y, z: 0 },
    idle: { x: x - 0.05, y, z: -0.45 },
    desk: { x: x + 0.5, y, z: 0.05 },
    door: { x, y, z: ROOM_DEPTH / 2 - 0.15 },
  };
}

export function roomKey(floor: number, roomIndex: number): string {
  return `${floor}:${roomIndex}`;
}
