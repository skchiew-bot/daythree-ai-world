import { useEffect, useMemo, useState } from "react";

import { useAgentRooms, useExternalAgentStatuses, useMissionTimeline, useMissions } from "@/api/hooks";
import { deriveExternalAgentState, deriveRoomAgentState, pickFocusMission, type AgentState } from "@/world/agentState";
import { toWorldAgents } from "@/world/renderPayload";
import { WorldCanvas } from "@/world/WorldCanvas";

const FALLBACK_FLOOR_COUNT = 5;

function describeScene(agents: { activity: string }[], externalCount: number): string {
  const count = (activity: string) => agents.filter((a) => a.activity === activity).length;
  return (
    `3D view of the agent apartment: ${agents.length} governed agents ` +
    `(${count("idle")} idle, ${count("assigned")} assigned, ${count("working")} working), ` +
    `plus ${externalCount} external agents in the front row.`
  );
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
  // Everything the 3D scene sees about a governed agent comes through this one
  // allow-list (ADR-013, data-warden D11). The tables below keep using the full rows.
  const worldAgents = useMemo(() => toWorldAgents(rooms), [rooms]);
  const agentStates = useMemo(
    () =>
      new Map<string, AgentState>(
        worldAgents.map((a) => [a.agent_id, deriveRoomAgentState(a, focusAgentId, timelineEventTypes)]),
      ),
    [worldAgents, focusAgentId, timelineEventTypes],
  );
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
  const externalNames = externalList.map((a) => a.name);
  const externalStates = new Map<string, AgentState>(
    externalList.map((a) => [a.name, deriveExternalAgentState(a, now)]),
  );

  return (
    <div>
      <h2>3D World</h2>
      <p style={{ color: "var(--text-muted)", marginTop: "-0.5rem" }}>
        Not part of the Phase 0 spec — an additive visualization of the real agent runtime. Every
        governed agent gets its own room in a per-tenant apartment (ADR-009). It sits at its room's
        desk when it has an active task; when it is idle it wanders out through the corridor to the
        lobby and back, on a schedule every browser computes the same way. Driven live by{" "}
        <code>GET /api/v1/agent-rooms</code>, not scripted. The row in front reflects any external
        agent — a Claude Code session, a script, anything — pinging{" "}
        <code>PUT /api/v1/external-agents/&#123;name&#125;/status</code>.
      </p>
      <div className="card" style={{ padding: 0, overflow: "hidden" }}>
        <WorldCanvas
          agents={worldAgents}
          agentStates={agentStates}
          floors={floors}
          externalNames={externalNames}
          externalStates={externalStates}
          label={describeScene(worldAgents, externalList.length)}
          describedBy="world-room-occupancy"
        />
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
