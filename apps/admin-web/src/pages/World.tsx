import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import { useExternalAgentStatuses, useMissionTimeline, useMissions } from "@/api/hooks";
import type { ExternalAgentStatus, Mission } from "@/types/api";

/** Visual state any avatar reacts to. Derived from real mission/task data or a real
 * external-agent status row polled from the API — nothing here is scripted. */
type AgentState = "idle" | "working" | "thinking" | "completed" | "failed";

const STATE_COLOR: Record<AgentState, number> = {
  idle: 0x60a5fa,
  working: 0xfacc15,
  thinking: 0xfacc15,
  completed: 0x4ade80,
  failed: 0xf87171,
};

const ATLAS_IDLE_POSITION = new THREE.Vector3(-2.2, 0, 1.5);
const ATLAS_DESK_POSITION = new THREE.Vector3(0, 0, -0.6);
const EXTERNAL_ROW_Z = 3.2;

/** Recently-completed/failed missions or external-agent pings still get their result
 * shown for a while so the state change is actually visible instead of snapping back
 * to idle the instant a fast (e.g. mock-provider, or an instantaneous status ping)
 * update lands. */
const RESULT_HOLD_MS = 6000;

function pickFocusMission(missions: Mission[] | undefined): Mission | null {
  if (!missions || missions.length === 0) return null;
  const running = missions.find((m) => m.status === "running");
  if (running) return running;
  const sorted = [...missions].sort((a, b) => {
    const aTime = a.started_at ?? a.created_at;
    const bTime = b.started_at ?? b.created_at;
    return new Date(bTime).getTime() - new Date(aTime).getTime();
  });
  return sorted[0] ?? null;
}

function deriveMissionAgentState(mission: Mission | null, timelineEventTypes: string[], now: number): AgentState {
  if (!mission) return "idle";

  if (mission.status === "completed" || mission.status === "failed") {
    const age = mission.completed_at ? now - new Date(mission.completed_at).getTime() : Infinity;
    if (age >= RESULT_HOLD_MS) return "idle";
    return mission.status === "completed" ? "completed" : "failed";
  }
  if (mission.status !== "running") return "idle";

  const requested = timelineEventTypes.filter((t) => t === "model.requested").length;
  const completed = timelineEventTypes.filter((t) => t === "model.completed" || t === "model.failed").length;
  return requested > completed ? "thinking" : "working";
}

function deriveExternalAgentState(agent: ExternalAgentStatus, now: number): AgentState {
  if (agent.status === "idle") return "idle";
  if (agent.status === "working") return "working";
  const age = now - new Date(agent.updated_at).getTime();
  if (age >= RESULT_HOLD_MS) return "idle";
  return agent.status === "done" ? "completed" : "failed";
}

interface AvatarHandle {
  group: THREE.Group;
  statusLightMaterial: THREE.MeshStandardMaterial;
  resultRing: THREE.Mesh;
  basePosition: THREE.Vector3;
  /** Only Atlas has somewhere else to walk to (the desk); external agents bob in place. */
  workPosition: THREE.Vector3;
}

function buildAvatar(scene: THREE.Scene, basePosition: THREE.Vector3, workPosition: THREE.Vector3): AvatarHandle {
  const group = new THREE.Group();
  const body = new THREE.Mesh(
    new THREE.CapsuleGeometry(0.28, 0.55, 6, 12),
    new THREE.MeshStandardMaterial({ color: 0xe2e8f0 }),
  );
  body.position.y = 0.62;
  group.add(body);
  const head = new THREE.Mesh(
    new THREE.SphereGeometry(0.22, 20, 16),
    new THREE.MeshStandardMaterial({ color: 0xf8fafc }),
  );
  head.position.y = 1.15;
  group.add(head);
  const statusLightMaterial = new THREE.MeshStandardMaterial({
    color: STATE_COLOR.idle,
    emissive: STATE_COLOR.idle,
    emissiveIntensity: 1.2,
  });
  const statusLight = new THREE.Mesh(new THREE.SphereGeometry(0.08, 16, 16), statusLightMaterial);
  statusLight.position.y = 1.5;
  group.add(statusLight);
  group.position.copy(basePosition);
  scene.add(group);

  const resultRing = new THREE.Mesh(
    new THREE.RingGeometry(0.4, 0.5, 32),
    new THREE.MeshBasicMaterial({ color: 0x4ade80, transparent: true, opacity: 0, side: THREE.DoubleSide }),
  );
  resultRing.rotation.x = -Math.PI / 2;
  resultRing.position.y = 0.02;
  scene.add(resultRing);

  return { group, statusLightMaterial, resultRing, basePosition, workPosition };
}

interface AvatarAnimState {
  ringElapsed: number;
  lastState: AgentState;
}

function updateAvatar(handle: AvatarHandle, anim: AvatarAnimState, state: AgentState, t: number, dt: number) {
  const { group, statusLightMaterial, resultRing } = handle;
  const isActive = state === "thinking" || state === "working";
  const targetPos = isActive || state === "completed" || state === "failed" ? handle.workPosition : handle.basePosition;

  group.position.x += (targetPos.x - group.position.x) * Math.min(1, dt * 2.5);
  group.position.z += (targetPos.z - group.position.z) * Math.min(1, dt * 2.5);

  const bobSpeed = isActive ? 6 : 1.6;
  const bobAmount = isActive ? 0.04 : 0.02;
  group.position.y = Math.sin(t * bobSpeed) * bobAmount;
  group.rotation.y += (state === "thinking" ? 0.6 : state === "working" ? 0.15 : 0.05) * dt;

  const color = STATE_COLOR[state];
  statusLightMaterial.color.setHex(color);
  statusLightMaterial.emissive.setHex(color);
  statusLightMaterial.emissiveIntensity = state === "thinking" ? 1.2 + Math.sin(t * 10) * 0.6 : 1.2;

  if (state !== anim.lastState && (state === "completed" || state === "failed")) {
    anim.ringElapsed = 0;
    (resultRing.material as THREE.MeshBasicMaterial).color.setHex(state === "completed" ? 0x4ade80 : 0xf87171);
  }
  anim.lastState = state;

  if (state === "completed" || state === "failed") {
    anim.ringElapsed += dt;
    const progress = Math.min(1, anim.ringElapsed / 1.4);
    resultRing.position.set(group.position.x, 0.02, group.position.z);
    resultRing.scale.setScalar(0.5 + progress * 3);
    (resultRing.material as THREE.MeshBasicMaterial).opacity = 0.6 * (1 - progress);
  } else {
    (resultRing.material as THREE.MeshBasicMaterial).opacity = 0;
  }
}

export function World() {
  const { data: missions } = useMissions();
  const { data: externalAgents } = useExternalAgentStatuses();
  const focusMission = pickFocusMission(missions);
  const { data: timeline } = useMissionTimeline(focusMission?.id);

  const timelineEventTypes = useMemo(() => timeline?.map((e) => e.event_type) ?? [], [timeline]);

  // A ticking clock, independent of query refetches: TanStack Query v5 only
  // re-renders the component when a *tracked* field changes, and structurally
  // identical poll results (an already-completed mission, an unchanged status row)
  // keep the same object reference (structural sharing) — so without this, "revert
  // to idle after RESULT_HOLD_MS" would never actually fire.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, []);

  const atlasState = deriveMissionAgentState(focusMission, timelineEventTypes, now);
  const externalList = externalAgents ?? [];

  const containerRef = useRef<HTMLDivElement>(null);
  const atlasStateRef = useRef<AgentState>(atlasState);
  atlasStateRef.current = atlasState;
  const externalStatesRef = useRef<Map<string, AgentState>>(new Map());
  externalStatesRef.current = new Map(externalList.map((a) => [a.name, deriveExternalAgentState(a, now)]));
  const externalNamesRef = useRef<string[]>([]);
  externalNamesRef.current = externalList.map((a) => a.name);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0f172a);
    scene.fog = new THREE.Fog(0x0f172a, 8, 22);

    const camera = new THREE.PerspectiveCamera(
      50,
      container.clientWidth / container.clientHeight,
      0.1,
      100,
    );
    camera.position.set(4, 4, 7);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0.6, 0);
    controls.enableDamping = true;
    controls.minDistance = 3;
    controls.maxDistance = 16;
    controls.maxPolarAngle = Math.PI / 2.05;

    scene.add(new THREE.AmbientLight(0xffffff, 0.5));
    const sun = new THREE.DirectionalLight(0xffffff, 1.1);
    sun.position.set(5, 8, 3);
    scene.add(sun);

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(20, 20),
      new THREE.MeshStandardMaterial({ color: 0x1e293b }),
    );
    floor.rotation.x = -Math.PI / 2;
    scene.add(floor);
    scene.add(new THREE.GridHelper(20, 20, 0x334155, 0x1e293b));

    const desk = new THREE.Group();
    const deskTop = new THREE.Mesh(
      new THREE.BoxGeometry(1.6, 0.08, 0.8),
      new THREE.MeshStandardMaterial({ color: 0x475569 }),
    );
    deskTop.position.y = 0.75;
    desk.add(deskTop);
    for (const [dx, dz] of [
      [-0.7, -0.3],
      [0.7, -0.3],
      [-0.7, 0.3],
      [0.7, 0.3],
    ]) {
      const leg = new THREE.Mesh(
        new THREE.BoxGeometry(0.08, 0.75, 0.08),
        new THREE.MeshStandardMaterial({ color: 0x334155 }),
      );
      leg.position.set(dx, 0.375, dz);
      desk.add(leg);
    }
    const monitor = new THREE.Mesh(
      new THREE.BoxGeometry(0.5, 0.35, 0.04),
      new THREE.MeshStandardMaterial({ color: 0x0f172a, emissive: 0x1d4ed8, emissiveIntensity: 0.3 }),
    );
    monitor.position.set(0, 1.0, -0.3);
    desk.add(monitor);
    desk.position.copy(ATLAS_DESK_POSITION);
    scene.add(desk);

    const atlas = buildAvatar(scene, ATLAS_IDLE_POSITION, ATLAS_DESK_POSITION.clone().add(new THREE.Vector3(0, 0, 0.7)));
    const atlasAnim: AvatarAnimState = { ringElapsed: 0, lastState: "idle" };

    // External agents: a growing/shrinking pool of avatars in their own row, one per
    // name currently reported by the API. Rebuilt (added/removed) each animation
    // frame by diffing against externalNamesRef, so a newly-registered agent (like
    // this very Claude Code session pinging in for the first time) gets an avatar
    // without needing a page reload.
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
    let lastSyncedNameKey = "";

    function animate() {
      frameId = requestAnimationFrame(animate);
      const dt = clock.getDelta();
      const t = clock.getElapsedTime();

      const nameKey = externalNamesRef.current.join("|");
      if (nameKey !== lastSyncedNameKey) {
        syncExternalAvatars();
        lastSyncedNameKey = nameKey;
      }

      updateAvatar(atlas, atlasAnim, atlasStateRef.current, t, dt);
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
        avatar's state is driven live by actual data polled from the API, not scripted: Atlas (near
        the desk) reflects real mission/task events; the row in front reflects any external agent —
        a Claude Code session, a script, anything — pinging{" "}
        <code>PUT /api/v1/external-agents/&#123;name&#125;/status</code>.
      </p>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <div ref={containerRef} style={{ width: "100%", height: "60vh" }} />
      </div>
      <div className="card" style={{ marginTop: "1rem" }}>
        <strong>Atlas</strong>{" "}
        {focusMission ? (
          <>
            — {focusMission.mission_code}: {focusMission.title}{" "}
            <span className={`badge status-${focusMission.status}`}>{focusMission.status}</span>
            <span style={{ color: "var(--text-muted)" }}> (avatar: {atlasState})</span>
          </>
        ) : (
          <span style={{ color: "var(--text-muted)" }}>
            No missions yet — start one in Mission Control to see it react here.
          </span>
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
