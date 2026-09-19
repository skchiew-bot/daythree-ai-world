import type { ExternalAgentStatus, Mission } from "@/types/api";

import type { WorldAgent } from "./renderPayload";

/** Visual state any avatar reacts to. Room-based avatars get this from the server's
 * activity field (already hold-window-adjusted); "thinking" is the one exception —
 * it stays timeline-derived and is layered on only for the focus mission's agent,
 * same as before ADR-009. */
export type AgentState = "idle" | "assigned" | "working" | "thinking" | "completed" | "failed";

/** How long a completed/failed external-agent ping keeps showing its result before
 * reverting to idle — mirrors the server's own RESULT_HOLD window for room activity
 * (services/api/routes/agent_rooms.py's _RESULT_HOLD_SECONDS). External agents still
 * need this computed client-side since external_agent_statuses carries no server-side
 * hold field. */
export const RESULT_HOLD_MS = 6000;

export function pickFocusMission(missions: Mission[] | undefined): Mission | null {
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

export function deriveRoomAgentState(
  room: WorldAgent,
  focusAgentId: string | null,
  timelineEventTypes: string[],
): AgentState {
  const base = room.activity;
  if (base !== "working" || room.agent_id !== focusAgentId) return base;

  const requested = timelineEventTypes.filter((t) => t === "model.requested").length;
  const completed = timelineEventTypes.filter((t) => t === "model.completed" || t === "model.failed").length;
  return requested > completed ? "thinking" : "working";
}

export function deriveExternalAgentState(agent: ExternalAgentStatus, now: number): AgentState {
  if (agent.status === "idle") return "idle";
  if (agent.status === "working") return "working";
  const age = now - new Date(agent.updated_at).getTime();
  if (age >= RESULT_HOLD_MS) return "idle";
  return agent.status === "done" ? "completed" : "failed";
}
