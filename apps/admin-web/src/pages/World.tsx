import { useEffect, useMemo, useRef, useState } from "react";

import { useAgentRooms, useExternalAgentStatuses, useMissionTimeline, useMissions } from "@/api/hooks";
import { deriveExternalAgentState, deriveRoomAgentState, pickFocusMission, type AgentState } from "@/world/agentState";
import { toWorldAgents, toWorldProjects } from "@/world/renderPayload";
import { describeScene } from "@/world/sceneLabel";
import { TownDirectory } from "@/world/TownDirectory";
import { WorldCanvas, type WorldCanvasApi } from "@/world/WorldCanvas";
import { WorldErrorBoundary } from "@/world/WorldErrorBoundary";

const FALLBACK_FLOOR_COUNT = 5;

export function World() {
  const { data: missions } = useMissions();
  const { data: roomsData } = useAgentRooms();
  const { data: externalAgents } = useExternalAgentStatuses();
  const focusMission = pickFocusMission(missions);
  const focusAgentId = focusMission?.assigned_agent_id ?? null;
  const { data: timeline } = useMissionTimeline(focusMission?.id);

  const timelineEventTypes = useMemo(() => timeline?.map((e) => e.event_type) ?? [], [timeline]);

  const rooms = useMemo(() => roomsData?.rooms ?? [], [roomsData]);
  // Everything the 3D scene sees about a governed agent comes through this one
  // allow-list (ADR-013, data-warden D11). The tables below keep using the full rows.
  const worldAgents = useMemo(() => toWorldAgents(rooms), [rooms]);
  // Projects reach the scene as {id, code} only (data-warden D13). The full rows, with
  // name, stay here for the HTML directory beside the canvas (operator decision O17).
  const projects = useMemo(() => roomsData?.projects ?? [], [roomsData]);
  const worldProjects = useMemo(() => toWorldProjects(projects), [projects]);
  const canvasApi = useRef<WorldCanvasApi>(null);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const focusOn = (key: string | null) => {
    setFocusKey(key);
    canvasApi.current?.focus(key);
  };
  const agentStates = useMemo(
    () =>
      new Map<string, AgentState>(
        worldAgents.map((a) => [a.agent_id, deriveRoomAgentState(a, focusAgentId, timelineEventTypes)]),
      ),
    [worldAgents, focusAgentId, timelineEventTypes],
  );
  const focusAgentRoom = rooms.find((r) => r.agent_id === focusAgentId);
  const focusAgentName = focusAgentRoom?.display_name ?? "Assigned agent";
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
  const externalNames = externalList.map((a) => a.name);
  const externalStates = new Map<string, AgentState>(
    externalList.map((a) => [a.name, deriveExternalAgentState(a, now)]),
  );

  return (
    <div>
      <h2>3D World</h2>
      <p style={{ color: "var(--text-muted)", marginTop: "-0.5rem" }}>
        Not part of the Phase 0 spec — an additive visualization of the real agent runtime. Every
        governed agent gets its own room in a per-tenant residence (ADR-009); when it is idle it
        wanders out through the corridor to the lobby and back. Each project is a building in the
        town (ADR-014), and a twin working on one commutes there over the roads, on foot, by
        bicycle or by motorbike; work with no project is done at the community hall. Click a
        building to focus it. Idle wandering and building placement are the same in every
        browser; when a commute starts depends on when that browser last polled. Driven live by{" "}
        <code>GET /api/v1/agent-rooms</code>, not scripted. The row in front reflects any external
        agent — a Claude Code session, a script, anything — pinging{" "}
        <code>PUT /api/v1/external-agents/&#123;name&#125;/status</code>.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "flex-start" }}>
        <div className="card" style={{ padding: 0, overflow: "hidden", flex: "3 1 30rem", minWidth: 0 }}>
          <WorldErrorBoundary>
            <WorldCanvas
              ref={canvasApi}
              agents={worldAgents}
              agentStates={agentStates}
              floors={floors}
              externalNames={externalNames}
              externalStates={externalStates}
              projects={worldProjects}
              label={describeScene(worldAgents, externalList.length, worldProjects.length)}
              describedBy="world-room-occupancy"
              onFocusChange={setFocusKey}
            />
          </WorldErrorBoundary>
        </div>
        <TownDirectory projects={projects} rooms={rooms} focusKey={focusKey} onFocus={focusOn} />
      </div>
      <div className="card" style={{ marginTop: "1rem" }}>
        <strong>Focus mission</strong>{" "}
        {focusMission ? (
          // Allow-listed fields only (data-warden D18): mission code, status, agent
          // display name, activity — never the free-text title (may carry a client name).
          <>
            — {focusAgentName}: {focusMission.mission_code}{" "}
            <span className={`badge status-${focusMission.status}`}>{focusMission.status}</span>{" "}
            {focusAgentRoom && (
              <span className={`badge status-${focusAgentRoom.activity}`}>{focusAgentRoom.activity}</span>
            )}
          </>
        ) : (
          <span style={{ color: "var(--text-muted)" }}>
            No missions yet — start one in Mission Control to see it react here.
          </span>
        )}
      </div>
      <div className="card" id="world-room-occupancy" style={{ marginTop: "1rem" }}>
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
          // Allow-listed fields only (data-warden D18): name, status, updated — never
          // job_description, a free-text field an external caller supplies unvalidated.
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
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
