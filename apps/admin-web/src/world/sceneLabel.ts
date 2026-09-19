import type { WorldAgent } from "./renderPayload";

const ACTIVITIES: readonly WorldAgent["activity"][] = ["idle", "assigned", "working", "completed", "failed"];

/** Text alternative for the 3D canvas. Counts only, never free text: no project code,
 * name, agent name or mission text (ADR-014 decision 5, data-warden D13). The
 * per-activity numbers add up to the total. */
export function describeScene(agents: readonly WorldAgent[], externalCount: number, projectBuildingCount = 0): string {
  const counts = ACTIVITIES.map((activity) => `${agents.filter((a) => a.activity === activity).length} ${activity}`);
  return (
    `3D view of the agent town: ${agents.length} governed agents (${counts.join(", ")}), ` +
    `plus ${externalCount} external agents in the front row. ` +
    `The town has a residence, a community hall and ${projectBuildingCount} project buildings on connected streets.`
  );
}
