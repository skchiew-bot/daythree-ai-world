import type { AgentRoom, ProjectSummary } from "@/types/api";

declare const worldAgentBrand: unique symbol;
declare const worldProjectBrand: unique symbol;

/** The only fields of a governed agent that may reach the 3D scene (ADR-013, data-warden
 * D11; ADR-014 decision 5 adds exactly `project_id`). No task title, mission objective,
 * error or reason text, note text, or job_description is drawn on an avatar, label, or
 * tooltip, so none of it may be in the render payload. Widening this list needs a
 * data-warden review.
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
  readonly project_id: string | null;
} & { readonly [worldAgentBrand]: true };

/** The only fields of a project that may reach the 3D scene (ADR-014 decision 5, data-
 * warden D13): `id` and `code`. `name` may be a client's name and never enters the
 * canvas; it stays in the HTML sidebar (operator decision O17). Same branding rule as
 * `WorldAgent`: a raw `ProjectSummary` (which has `name`) does not satisfy it. */
export type WorldProject = {
  readonly id: string;
  readonly code: string;
} & { readonly [worldProjectBrand]: true };

/** The single allow-list builder for agents. It copies fields one by one and never
 * spreads an API row. */
export function toWorldAgent(room: AgentRoom): WorldAgent {
  return {
    agent_id: room.agent_id,
    display_name: room.display_name,
    activity: room.activity,
    floor: room.floor,
    room_index: room.room_index,
    project_id: room.project_id,
  } as WorldAgent;
}

export function toWorldAgents(rooms: readonly AgentRoom[]): WorldAgent[] {
  return rooms.map(toWorldAgent);
}

/** The single allow-list builder for projects, field by field, no spread. */
export function toWorldProject(project: ProjectSummary): WorldProject {
  return {
    id: project.id,
    code: project.code,
  } as WorldProject;
}

export function toWorldProjects(projects: readonly ProjectSummary[]): WorldProject[] {
  return projects.map(toWorldProject);
}
