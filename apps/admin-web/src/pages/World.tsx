import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import { useMissionTimeline, useMissions } from "@/api/hooks";
import type { Mission } from "@/types/api";

/** Visual state the avatar reacts to. Derived from real mission/task data polled
 * from the API — nothing here is scripted or randomized. */
type AgentState = "idle" | "working" | "thinking" | "completed" | "failed";

const STATE_COLOR: Record<AgentState, number> = {
  idle: 0x60a5fa,
  working: 0xfacc15,
  thinking: 0xfacc15,
  completed: 0x4ade80,
  failed: 0xf87171,
};

const IDLE_POSITION = new THREE.Vector3(-2.2, 0, 1.5);
const DESK_POSITION = new THREE.Vector3(0, 0, -0.6);

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

/** Recently-completed/failed missions still get their result shown for a while so
 * the state change is actually visible instead of snapping back to idle the instant
 * a fast (e.g. mock-provider) mission finishes. */
const RESULT_HOLD_MS = 6000;

function deriveAgentState(mission: Mission | null, timelineEventTypes: string[], now: number): AgentState {
  if (!mission) return "idle";

  if (mission.status === "completed") {
    const age = mission.completed_at ? now - new Date(mission.completed_at).getTime() : Infinity;
    return age < RESULT_HOLD_MS ? "completed" : "idle";
  }
  if (mission.status === "failed") {
    const age = mission.completed_at ? now - new Date(mission.completed_at).getTime() : Infinity;
    return age < RESULT_HOLD_MS ? "failed" : "idle";
  }
  if (mission.status !== "running") return "idle";

  const requested = timelineEventTypes.filter((t) => t === "model.requested").length;
  const completed = timelineEventTypes.filter((t) => t === "model.completed" || t === "model.failed").length;
  return requested > completed ? "thinking" : "working";
}

export function World() {
  const { data: missions } = useMissions();
  const focusMission = pickFocusMission(missions);
  const { data: timeline } = useMissionTimeline(focusMission?.id);

  const timelineEventTypes = useMemo(() => timeline?.map((e) => e.event_type) ?? [], [timeline]);

  // A ticking clock, independent of query refetches: TanStack Query v5 only
  // re-renders the component when a *tracked* field changes, and a completed
  // mission's data is structurally identical poll to poll (same object, thanks to
  // structural sharing) — so without this, "revert to idle after RESULT_HOLD_MS"
  // would never actually fire, since nothing would trigger the recomputation.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(id);
  }, []);

  const agentState = deriveAgentState(focusMission, timelineEventTypes, now);

  const containerRef = useRef<HTMLDivElement>(null);
  const agentStateRef = useRef<AgentState>(agentState);
  agentStateRef.current = agentState;

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
    camera.position.set(4, 4, 6);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0.6, 0);
    controls.enableDamping = true;
    controls.minDistance = 3;
    controls.maxDistance = 14;
    controls.maxPolarAngle = Math.PI / 2.05;

    scene.add(new THREE.AmbientLight(0xffffff, 0.5));
    const sun = new THREE.DirectionalLight(0xffffff, 1.1);
    sun.position.set(5, 8, 3);
    scene.add(sun);

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(16, 16),
      new THREE.MeshStandardMaterial({ color: 0x1e293b }),
    );
    floor.rotation.x = -Math.PI / 2;
    scene.add(floor);
    scene.add(new THREE.GridHelper(16, 16, 0x334155, 0x1e293b));

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
    desk.position.copy(DESK_POSITION);
    scene.add(desk);

    // Agent avatar: capsule body + sphere head + a state-colored "status light".
    const agent = new THREE.Group();
    const body = new THREE.Mesh(
      new THREE.CapsuleGeometry(0.28, 0.55, 6, 12),
      new THREE.MeshStandardMaterial({ color: 0xe2e8f0 }),
    );
    body.position.y = 0.62;
    agent.add(body);
    const head = new THREE.Mesh(
      new THREE.SphereGeometry(0.22, 20, 16),
      new THREE.MeshStandardMaterial({ color: 0xf8fafc }),
    );
    head.position.y = 1.15;
    agent.add(head);
    const statusLightMaterial = new THREE.MeshStandardMaterial({
      color: STATE_COLOR.idle,
      emissive: STATE_COLOR.idle,
      emissiveIntensity: 1.2,
    });
    const statusLight = new THREE.Mesh(new THREE.SphereGeometry(0.08, 16, 16), statusLightMaterial);
    statusLight.position.y = 1.5;
    agent.add(statusLight);
    agent.position.copy(IDLE_POSITION);
    scene.add(agent);

    // Result ring: scales up + fades out on completion/failure, otherwise hidden.
    const resultRing = new THREE.Mesh(
      new THREE.RingGeometry(0.4, 0.5, 32),
      new THREE.MeshBasicMaterial({ color: 0x4ade80, transparent: true, opacity: 0, side: THREE.DoubleSide }),
    );
    resultRing.rotation.x = -Math.PI / 2;
    resultRing.position.y = 0.02;
    scene.add(resultRing);

    function handleResize() {
      if (!container) return;
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    }
    window.addEventListener("resize", handleResize);

    let frameId: number;
    const clock = new THREE.Clock();
    let ringElapsed = 0;
    let lastState: AgentState = "idle";

    function animate() {
      frameId = requestAnimationFrame(animate);
      const dt = clock.getDelta();
      const t = clock.getElapsedTime();
      const state = agentStateRef.current;

      const targetPos = state === "idle" ? IDLE_POSITION : DESK_POSITION;
      agent.position.x += (targetPos.x - agent.position.x) * Math.min(1, dt * 2.5);
      agent.position.z += (targetPos.z + 0.7 - agent.position.z) * Math.min(1, dt * 2.5);

      const bobSpeed = state === "thinking" || state === "working" ? 6 : 1.6;
      const bobAmount = state === "thinking" || state === "working" ? 0.04 : 0.02;
      agent.position.y = Math.sin(t * bobSpeed) * bobAmount;
      agent.rotation.y += (state === "thinking" ? 0.6 : state === "working" ? 0.15 : 0.05) * dt;

      const color = STATE_COLOR[state];
      statusLightMaterial.color.setHex(color);
      statusLightMaterial.emissive.setHex(color);
      statusLightMaterial.emissiveIntensity = state === "thinking" ? 1.2 + Math.sin(t * 10) * 0.6 : 1.2;

      if (state !== lastState && (state === "completed" || state === "failed")) {
        ringElapsed = 0;
        (resultRing.material as THREE.MeshBasicMaterial).color.setHex(
          state === "completed" ? 0x4ade80 : 0xf87171,
        );
      }
      lastState = state;

      if (state === "completed" || state === "failed") {
        ringElapsed += dt;
        const progress = Math.min(1, ringElapsed / 1.4);
        resultRing.position.set(agent.position.x, 0.02, agent.position.z);
        resultRing.scale.setScalar(0.5 + progress * 3);
        (resultRing.material as THREE.MeshBasicMaterial).opacity = 0.6 * (1 - progress);
      } else {
        (resultRing.material as THREE.MeshBasicMaterial).opacity = 0;
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
        Not part of the Phase 0 spec — an additive visualization of the real agent runtime. The
        avatar's state is driven live by actual mission/task data polled from the API, not scripted.
      </p>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <div ref={containerRef} style={{ width: "100%", height: "60vh" }} />
      </div>
      <div className="card" style={{ marginTop: "1rem" }}>
        {focusMission ? (
          <>
            <strong>{focusMission.mission_code}</strong> — {focusMission.title}{" "}
            <span className={`badge status-${focusMission.status}`}>{focusMission.status}</span>
            <div style={{ color: "var(--text-muted)", marginTop: "0.4rem" }}>
              Avatar state: <strong>{agentState}</strong>
            </div>
          </>
        ) : (
          <span style={{ color: "var(--text-muted)" }}>
            No missions yet — start one in Mission Control to see the agent react here.
          </span>
        )}
      </div>
    </div>
  );
}
