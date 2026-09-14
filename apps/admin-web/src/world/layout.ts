import * as THREE from "three";

/** Pure function of (floor, roomIndex) — never array order — so registering an
 * unrelated agent never moves anyone else's room (ADR-009). */
export const ROOMS_PER_FLOOR = 4;
export const ROOM_WIDTH = 2.4;
export const ROOM_DEPTH = 2.2;
export const FLOOR_HEIGHT = 1.9;

export interface RoomAnchors {
  center: THREE.Vector3;
  idle: THREE.Vector3;
  desk: THREE.Vector3;
  deskProp: THREE.Vector3;
}

export function roomAnchors(floor: number, roomIndex: number): RoomAnchors {
  const totalWidth = ROOMS_PER_FLOOR * ROOM_WIDTH;
  const startX = -totalWidth / 2 + ROOM_WIDTH / 2;
  const x = startX + (roomIndex - 1) * ROOM_WIDTH;
  const y = (floor - 1) * FLOOR_HEIGHT;
  const z = 0;

  return {
    center: new THREE.Vector3(x, y, z),
    idle: new THREE.Vector3(x - ROOM_WIDTH * 0.22, y, z - ROOM_DEPTH * 0.25),
    desk: new THREE.Vector3(x + ROOM_WIDTH * 0.12, y, z + ROOM_DEPTH * 0.2),
    deskProp: new THREE.Vector3(x + ROOM_WIDTH * 0.12, y, z + ROOM_DEPTH * 0.28),
  };
}

export function roomKey(floor: number, roomIndex: number): string {
  return `${floor}:${roomIndex}`;
}
