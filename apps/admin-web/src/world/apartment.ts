import * as THREE from "three";

import { STATE_COLOR } from "./avatar";
import type { AgentState } from "./agentState";
import { GeometryBatcher } from "./batch";
import { addLobbyFurniture, addRoomFurniture, accentFor } from "./furniture";
import {
  BUILDING_WIDTH,
  CORRIDOR_DEPTH,
  floorY,
  ROOM_DEPTH,
  ROOM_WIDTH,
  ROOMS_PER_FLOOR,
  roomCenterX,
  roomKey,
} from "./layout";
import type { MaterialSet } from "./materials";

export interface RoomPanelHandle {
  panelMaterial: THREE.MeshStandardMaterial;
}

export interface ApartmentHandle {
  group: THREE.Group;
  panels: Map<string, RoomPanelHandle>;
  floors: number;
  /** Frees what this building owns. The shared materials belong to the scene. */
  dispose: () => void;
}

const WALL_HEIGHT = 1.8;
const DIVIDER_HEIGHT = 1.1;
const HEADER_Y = 1.62;
const FLAT_MATERIALS = new Set(["floorWood", "corridorTile", "lobbyRug"]);

function castsShadow(material: string): boolean {
  return !FLAT_MATERIALS.has(material) && !material.startsWith("rug");
}

function addFloorShell(b: GeometryBatcher, floor: number): void {
  const y = floorY(floor);
  const corridorZ = ROOM_DEPTH / 2 + CORRIDOR_DEPTH / 2;

  b.box("corridorTile", BUILDING_WIDTH + 0.2, 0.1, CORRIDOR_DEPTH, 0, y - 0.05, corridorZ, { uvTile: 1 });
  for (let roomIndex = 1; roomIndex <= ROOMS_PER_FLOOR; roomIndex++) {
    const cx = roomCenterX(roomIndex);
    b.box("floorWood", ROOM_WIDTH, 0.1, ROOM_DEPTH, cx, y - 0.05, 0, { uvTile: 1.2 });
    b.box(`wall${accentFor(floor, roomIndex)}`, ROOM_WIDTH, WALL_HEIGHT, 0.1, cx, y + WALL_HEIGHT / 2, -ROOM_DEPTH / 2 - 0.05);
    b.box("trim", ROOM_WIDTH - 0.1, 0.14, 0.05, cx, y + HEADER_Y, ROOM_DEPTH / 2);
  }
  for (let line = 0; line <= ROOMS_PER_FLOOR; line++) {
    const x = -BUILDING_WIDTH / 2 + line * ROOM_WIDTH;
    b.box("divider", 0.06, DIVIDER_HEIGHT, ROOM_DEPTH, x, y + DIVIDER_HEIGHT / 2, 0);
  }
}

function addRailing(b: GeometryBatcher, floor: number): void {
  const y = floorY(floor);
  const z = ROOM_DEPTH / 2 + CORRIDOR_DEPTH - 0.03;
  const width = BUILDING_WIDTH + 0.2;
  b.box("railing", width, 0.04, 0.05, 0, y + 0.5, z);
  b.box("railing", width, 0.025, 0.03, 0, y + 0.25, z);
  for (let x = -BUILDING_WIDTH / 2; x <= BUILDING_WIDTH / 2 + 0.01; x += ROOM_WIDTH / 2) {
    b.box("railing", 0.04, 0.5, 0.04, x, y + 0.25, z);
  }
}

function addPanels(floor: number, panels: Map<string, RoomPanelHandle>, group: THREE.Group): void {
  const y = floorY(floor);
  const geometry = new THREE.BoxGeometry(0.4, 0.09, 0.02);
  for (let roomIndex = 1; roomIndex <= ROOMS_PER_FLOOR; roomIndex++) {
    const panelMaterial = new THREE.MeshStandardMaterial({
      color: STATE_COLOR.idle,
      emissive: STATE_COLOR.idle,
      emissiveIntensity: 0.6,
    });
    const panel = new THREE.Mesh(geometry, panelMaterial);
    panel.position.set(roomCenterX(roomIndex), y + HEADER_Y, ROOM_DEPTH / 2 + 0.035);
    group.add(panel);
    panels.set(roomKey(floor, roomIndex), { panelMaterial });
  }
}

/** Builds the whole building: `floors` x ROOMS_PER_FLOOR rooms (occupied or not, so the
 * size reads correctly before every room has an occupant), a corridor gallery with a
 * lobby on every floor, and a status panel over each room's open front. All static
 * geometry is merged per material. */
export function buildApartment(scene: THREE.Scene, floors: number, materials: MaterialSet): ApartmentHandle {
  const batch = new GeometryBatcher();
  const panels = new Map<string, RoomPanelHandle>();

  for (let floor = 1; floor <= floors; floor++) {
    addFloorShell(batch, floor);
    addRailing(batch, floor);
    addLobbyFurniture(batch, floor);
    for (let roomIndex = 1; roomIndex <= ROOMS_PER_FLOOR; roomIndex++) addRoomFurniture(batch, floor, roomIndex);
  }

  const group = batch.build(materials.all, castsShadow);
  const panelGroup = new THREE.Group();
  for (let floor = 1; floor <= floors; floor++) addPanels(floor, panels, panelGroup);
  group.add(panelGroup);
  scene.add(group);

  return {
    group,
    panels,
    floors,
    dispose: () => {
      scene.remove(group);
      group.traverse((node) => (node as THREE.Mesh).geometry?.dispose());
      panels.forEach((panel) => panel.panelMaterial.dispose());
    },
  };
}

export function tintRoomPanel(handle: ApartmentHandle, floor: number, roomIndex: number, state: AgentState): void {
  const panel = handle.panels.get(roomKey(floor, roomIndex));
  if (!panel) return;
  const color = STATE_COLOR[state];
  panel.panelMaterial.color.setHex(color);
  panel.panelMaterial.emissive.setHex(color);
}
