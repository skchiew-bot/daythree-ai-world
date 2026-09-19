import type { AgentRoom } from "@/types/api";

/** The only fields of a governed agent that may reach the 3D scene (ADR-013, data-warden
 * D11). No task title, mission objective, error or reason text, note text, or
 * job_description is drawn on an avatar, label, or tooltip, so none of it may be in the
 * render payload. Widening this list needs a data-warden review. */
export interface WorldAgent {
  agent_id: string;
  display_name: string;
  activity: AgentRoom["activity"];
  floor: number;
  room_index: number;
}

/** The single allow-list builder. It copies fields one by one and never spreads an API row. */
export function toWorldAgent(room: AgentRoom): WorldAgent {
  return {
    agent_id: room.agent_id,
    display_name: room.display_name,
    activity: room.activity,
    floor: room.floor,
    room_index: room.room_index,
  };
}

export function toWorldAgents(rooms: readonly AgentRoom[]): WorldAgent[] {
  return rooms.map(toWorldAgent);
}
