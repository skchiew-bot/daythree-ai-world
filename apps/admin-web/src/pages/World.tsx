import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import { useAgentRooms, useExternalAgentStatuses, useMissionTimeline, useMissions } from "@/api/hooks";
import type { AgentRoom } from "@/types/api";
import {
  deriveExternalAgentState,
  deriveRoomAgentState,
  pickFocusMission,
  type AgentState,
} from "@/world/agentState";
import { buildApartment, disposeApartment, tintRoomPanel, type ApartmentHandle } from "@/world/apartment";
import { buildAvatar, snapAvatar, updateAvatar, type AvatarAnimState, type AvatarHandle } from "@/world/avatar";
import { roomAnchors, roomKey } from "@/world/layout";

const EXTERNAL_ROW_Z = 4.4;
const FALLBACK_FLOOR_COUNT = 5;

interface RoomAvatarEntry {
  handle: AvatarHandle;
  anim: AvatarAnimState;
  roomKey: string;
}

export function World() {
  const { data: missions } = useMissions();
  const { data: roomsData } = useAgentRooms();
  const { data: externalAgents } = useExternalAgentStatuses();
  const focusMission = pickFocusMission(missions);
  const focusAgentId = focusMission?.assigned_agent_id ?? null;
  const { data: timeline } = useMissionTimeline(focusMission?.id);

  const timelineEventTypes = useMemo(() => timeline?.map((e) => e.event_type) ?? [], [timeline]);

  const rooms = useMemo(() => roomsData?.rooms ?? [], [roomsData]);
  const focusAgentName = rooms.find((r) => r.agent_id === focusAgentId)?.display_name ?? "Assigned agent";
  const floors = Math.max(
    roomsData?.default_floor_count ?? FALLBACK_FLOOR_COUNT,
    ...rooms.map((r) => r.floor),
    1,
  );

  // External-agent result-hold logic still needs a ticking clock (deriveExternalAgentState
  // computes age client-side); room activity no longer does — the server already
  // recomputes it fresh on every 3s poll, so a changed value there re-renders on its own.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, []);

  const externalList = externalAgents ?? [];

  const containerRef = useRef<HTMLDivElement>(null);
  const roomsRef = useRef<AgentRoom[]>(rooms);
  roomsRef.current = rooms;
  const roomStatesRef = useRef<Map<string, AgentState>>(new Map());
  roomStatesRef.current = new Map(
    rooms.map((r) => [r.agent_id, deriveRoomAgentState(r, focusAgentId, timelineEventTypes)]),
  );
  const floorsRef = useRef<number>(floors);
  floorsRef.current = floors;

  const externalStatesRef = useRef<Map<string, AgentState>>(new Map());
  externalStatesRef.current = new Map(externalList.map((a) => [a.name, deriveExternalAgentState(a, now)]));
  const externalNamesRef = useRef<string[]>([]);
  externalNamesRef.current = externalList.map((a) => a.name);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0f172a);
    scene.fog = new THREE.Fog(0x0f172a, 10, 30);

    const camera = new THREE.PerspectiveCamera(50, container.clientWidth / container.clientHeight, 0.1, 100);
    camera.position.set(6, 6, 11);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 2.5, 0);
    controls.enableDamping = true;
    controls.minDistance = 3;
    controls.maxDistance = 26;
    controls.maxPolarAngle = Math.PI / 2.05;

    scene.add(new THREE.AmbientLight(0xffffff, 0.5));
    const sun = new THREE.DirectionalLight(0xffffff, 1.1);
    sun.position.set(6, 10, 4);
    scene.add(sun);

    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(28, 28),
      new THREE.MeshStandardMaterial({ color: 0x1e293b }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = -0.05;
    scene.add(ground);
    scene.add(new THREE.GridHelper(28, 28, 0x334155, 0x1e293b));

    let apartment: ApartmentHandle = buildApartment(scene, floorsRef.current);
    let lastSyncedFloors = floorsRef.current;

    // Room-based avatars: one per governed agent that currently has a room, keyed by
    // agent_id (never array index — a room's position comes only from its own
    // floor/room_index, per ADR-009).
    const roomAvatars = new Map<string, RoomAvatarEntry>();

    function syncRoomAvatars() {
      const currentRooms = roomsRef.current;
      const currentIds = new Set(currentRooms.map((r) => r.agent_id));

      for (const [agentId, entry] of roomAvatars) {
        if (!currentIds.has(agentId)) {
          scene.remove(entry.handle.group);
          scene.remove(entry.handle.resultRing);
          roomAvatars.delete(agentId);
        }
      }

      for (const room of currentRooms) {
        const key = roomKey(room.floor, room.room_index);
        const anchors = roomAnchors(room.floor, room.room_index);
        const existing = roomAvatars.get(room.agent_id);

        if (!existing) {
          const handle = buildAvatar(scene, anchors.idle, anchors.desk);
          roomAvatars.set(room.agent_id, { handle, anim: { ringElapsed: 0, lastState: "idle" }, roomKey: key });
          continue;
        }

        if (existing.roomKey !== key) {
          // Reassigned to a different room (suspend/reactivate) — snap rather than
          // lerp across the building.
          existing.handle.basePosition.copy(anchors.idle);
          existing.handle.workPosition.copy(anchors.desk);
          const state = roomStatesRef.current.get(room.agent_id) ?? "idle";
          snapAvatar(existing.handle, state !== "idle");
          existing.roomKey = key;
        }
      }
    }

    // External agents: unchanged from the pre-ADR-009 desk layout — a growing/
    // shrinking pool of avatars in their own row in front of the building.
    const externalHandles = new Map<string, { handle: AvatarHandle; anim: AvatarAnimState }>();

    function slotPosition(index: number, total: number): THREE.Vector3 {
      const spacing = 1.6;
      const startX = -((total - 1) * spacing) / 2;
      return new THREE.Vector3(startX + index * spacing, 0, EXTERNAL_ROW_Z);
    }

    function syncExternalAvatars() {
      const names = externalNamesRef.current;
      for (const [name, entry] of externalHandles) {
        if (!names.includes(name)) {
          scene.remove(entry.handle.group);
          scene.remove(entry.handle.resultRing);
          externalHandles.delete(name);
        }
      }
      names.forEach((name, i) => {
        const pos = slotPosition(i, names.length);
        const entry = externalHandles.get(name);
        if (entry) {
          entry.handle.basePosition.copy(pos);
          entry.handle.workPosition.copy(pos);
        } else {
          const handle = buildAvatar(scene, pos, pos.clone());
          externalHandles.set(name, { handle, anim: { ringElapsed: 0, lastState: "idle" } });
        }
      });
    }

    function handleResize() {
      if (!container) return;
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    }
    window.addEventListener("resize", handleResize);

    let frameId: number;
    const clock = new THREE.Clock();
    let lastSyncedRoomKey = "";
    let lastSyncedNameKey = "";

    function animate() {
      frameId = requestAnimationFrame(animate);
      const dt = clock.getDelta();
      const t = clock.getElapsedTime();

      if (floorsRef.current !== lastSyncedFloors) {
        disposeApartment(scene, apartment);
        apartment = buildApartment(scene, floorsRef.current);
        lastSyncedFloors = floorsRef.current;
      }

      const roomSyncKey = roomsRef.current.map((r) => `${r.agent_id}:${r.floor}:${r.room_index}`).join("|");
      if (roomSyncKey !== lastSyncedRoomKey) {
        syncRoomAvatars();
        lastSyncedRoomKey = roomSyncKey;
      }

      const nameKey = externalNamesRef.current.join("|");
      if (nameKey !== lastSyncedNameKey) {
        syncExternalAvatars();
        lastSyncedNameKey = nameKey;
      }

      for (const room of roomsRef.current) {
        const entry = roomAvatars.get(room.agent_id);
        if (!entry) continue;
        const state = roomStatesRef.current.get(room.agent_id) ?? "idle";
        updateAvatar(entry.handle, entry.anim, state, t, dt);
        tintRoomPanel(apartment, room.floor, room.room_index, state);
      }

      for (const [name, entry] of externalHandles) {
        const state = externalStatesRef.current.get(name) ?? "idle";
        updateAvatar(entry.handle, entry.anim, state, t, dt);
      }

      controls.update();
      renderer.render(scene, camera);
    }
    animate();

    return () => {
      cancelAnimationFrame(frameId);
      window.removeEventListener("resize", handleResize);
      controls.dispose();
      renderer.dispose();
      container.removeChild(renderer.domElement);
    };
  }, []);

  return (
    <div>
      <h2>3D World</h2>
      <p style={{ color: "var(--text-muted)", marginTop: "-0.5rem" }}>
        Not part of the Phase 0 spec — an additive visualization of the real agent runtime. Every
        governed agent gets its own room in a per-tenant apartment (ADR-009), walking to its room's
        desk when it has an active task and back to idle when it doesn't — driven live by{" "}
        <code>GET /api/v1/agent-rooms</code>, not scripted. The row in front reflects any external
        agent — a Claude Code session, a script, anything — pinging{" "}
        <code>PUT /api/v1/external-agents/&#123;name&#125;/status</code>.
      </p>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <div ref={containerRef} style={{ width: "100%", height: "60vh" }} />
      </div>
      <div className="card" style={{ marginTop: "1rem" }}>
        <strong>Focus mission</strong>{" "}
        {focusMission ? (
          <>
            — {focusAgentName}: {focusMission.mission_code}: {focusMission.title}{" "}
            <span className={`badge status-${focusMission.status}`}>{focusMission.status}</span>
          </>
        ) : (
          <span style={{ color: "var(--text-muted)" }}>
            No missions yet — start one in Mission Control to see it react here.
          </span>
        )}
      </div>
      <div className="card" style={{ marginTop: "1rem" }}>
        <strong>Room occupancy</strong>
        {rooms.length === 0 ? (
          <p style={{ color: "var(--text-muted)" }}>No governed agents registered yet.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Floor</th>
                <th>Room</th>
                <th>Agent</th>
                <th>Activity</th>
              </tr>
            </thead>
            <tbody>
              {[...rooms]
                .sort((a, b) => a.floor - b.floor || a.room_index - b.room_index)
                .map((room) => (
                  <tr key={room.agent_id}>
                    <td>{room.floor}</td>
                    <td>{room.room_index}</td>
                    <td>{room.display_name}</td>
                    <td>
                      <span className={`badge status-${room.activity}`}>{room.activity}</span>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="card" style={{ marginTop: "1rem" }}>
        <strong>External agents</strong>
        {externalList.length === 0 ? (
          <p style={{ color: "var(--text-muted)" }}>
            None connected yet. Any authenticated caller can register by calling
            {" "}
            <code>PUT /api/v1/external-agents/&#123;name&#125;/status</code> with a body like{" "}
            <code>{`{"status": "working", "job_description": "..."}`}</code>.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Job</th>
                <th>Updated</th>
              </tr>
            </thead>
            <tbody>
              {externalList.map((agent) => (
                <tr key={agent.name}>
                  <td>{agent.name}</td>
                  <td>
                    <span className={`badge status-${agent.status}`}>{agent.status}</span>
                  </td>
                  <td>{agent.job_description ?? "—"}</td>
                  <td>{new Date(agent.updated_at).toLocaleTimeString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
