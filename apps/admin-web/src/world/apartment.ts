import * as THREE from "three";

import { FLOOR_HEIGHT, ROOM_DEPTH, ROOM_WIDTH, ROOMS_PER_FLOOR, roomAnchors, roomKey } from "./layout";
import { STATE_COLOR } from "./avatar";
import type { AgentState } from "./agentState";

export interface RoomPanelHandle {
  panelMaterial: THREE.MeshStandardMaterial;
}

export interface ApartmentHandle {
  group: THREE.Group;
  panels: Map<string, RoomPanelHandle>;
  floors: number;
}

/** Builds every room shell up to `floors` x ROOMS_PER_FLOOR (occupied or not) — an
 * empty room still shows a desk and an idle-tinted panel, so the building's size
 * reads correctly even before all rooms have occupants. */
export function buildApartment(scene: THREE.Scene, floors: number): ApartmentHandle {
  const group = new THREE.Group();
  const panels = new Map<string, RoomPanelHandle>();
  const totalWidth = ROOMS_PER_FLOOR * ROOM_WIDTH;

  for (let floor = 1; floor <= floors; floor++) {
    const y = (floor - 1) * FLOOR_HEIGHT;

    const slab = new THREE.Mesh(
      new THREE.BoxGeometry(totalWidth + 0.4, 0.1, ROOM_DEPTH + 0.4),
      new THREE.MeshStandardMaterial({ color: 0x1e293b }),
    );
    slab.position.set(0, y - 0.05, 0);
    group.add(slab);

    for (let roomIndex = 1; roomIndex <= ROOMS_PER_FLOOR; roomIndex++) {
      const anchors = roomAnchors(floor, roomIndex);

      if (roomIndex > 1) {
        const divider = new THREE.Mesh(
          new THREE.BoxGeometry(0.04, FLOOR_HEIGHT * 0.65, ROOM_DEPTH),
          new THREE.MeshStandardMaterial({ color: 0x334155 }),
        );
        divider.position.set(anchors.center.x - ROOM_WIDTH / 2, y + (FLOOR_HEIGHT * 0.65) / 2, 0);
        group.add(divider);
      }

      const desk = new THREE.Group();
      const deskTop = new THREE.Mesh(
        new THREE.BoxGeometry(0.85, 0.06, 0.45),
        new THREE.MeshStandardMaterial({ color: 0x475569 }),
      );
      deskTop.position.set(anchors.deskProp.x, y + 0.45, anchors.deskProp.z);
      desk.add(deskTop);
      const monitor = new THREE.Mesh(
        new THREE.BoxGeometry(0.28, 0.2, 0.03),
        new THREE.MeshStandardMaterial({ color: 0x0f172a, emissive: 0x1d4ed8, emissiveIntensity: 0.3 }),
      );
      monitor.position.set(anchors.deskProp.x, y + 0.65, anchors.deskProp.z - 0.18);
      desk.add(monitor);
      group.add(desk);

      const panelMaterial = new THREE.MeshStandardMaterial({
        color: STATE_COLOR.idle, emissive: STATE_COLOR.idle, emissiveIntensity: 0.4,
      });
      const panel = new THREE.Mesh(new THREE.BoxGeometry(0.32, 0.14, 0.02), panelMaterial);
      panel.position.set(anchors.center.x, y + 0.95, ROOM_DEPTH / 2 + 0.01);
      group.add(panel);
      panels.set(roomKey(floor, roomIndex), { panelMaterial });
    }
  }

  scene.add(group);
  return { group, panels, floors };
}

export function tintRoomPanel(handle: ApartmentHandle, floor: number, roomIndex: number, state: AgentState) {
  const panel = handle.panels.get(roomKey(floor, roomIndex));
  if (!panel) return;
  const color = STATE_COLOR[state];
  panel.panelMaterial.color.setHex(color);
  panel.panelMaterial.emissive.setHex(color);
}

export function disposeApartment(scene: THREE.Scene, handle: ApartmentHandle) {
  scene.remove(handle.group);
}
