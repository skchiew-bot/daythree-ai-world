import type { AgentRoom } from "@/types/api";

declare const worldAgentBrand: unique symbol;

/** The only fields of a governed agent that may reach the 3D scene (ADR-013, data-warden
 * D11). No task title, mission objective, error or reason text, note text, or
 * job_description is drawn on an avatar, label, or tooltip, so none of it may be in the
 * render payload. Widening this list needs a data-warden review.
 *
 * The type is branded: an `AgentRoom`, or any object literal, does not satisfy it, so
 * only `toWorldAgent` below can produce one and the compiler rejects raw API rows
 * anywhere the scene is fed (see renderPayload.types.test.ts). */
export type WorldAgent = {
  readonly agent_id: string;
  readonly display_name: string;
  readonly activity: AgentRoom["activity"];
  readonly floor: number;
  readonly room_index: number;
} & { readonly [worldAgentBrand]: true };

/** The single allow-list builder. It copies fields one by one and never spreads an API row. */
export function toWorldAgent(room: AgentRoom): WorldAgent {
  return {
    agent_id: room.agent_id,
    display_name: room.display_name,
    activity: room.activity,
    floor: room.floor,
    room_index: room.room_index,
  } as WorldAgent;
}

export function toWorldAgents(rooms: readonly AgentRoom[]): WorldAgent[] {
  return rooms.map(toWorldAgent);
}
