import type { WorldAgent } from "./renderPayload";

const ACTIVITIES: readonly WorldAgent["activity"][] = ["idle", "assigned", "working", "completed", "failed"];

/** Text alternative for the 3D canvas. Counts only, never free text, and the per-activity
 * numbers add up to the total. */
export function describeScene(agents: readonly WorldAgent[], externalCount: number): string {
  const counts = ACTIVITIES.map((activity) => `${agents.filter((a) => a.activity === activity).length} ${activity}`);
  return (
    `3D view of the agent apartment: ${agents.length} governed agents (${counts.join(", ")}), ` +
    `plus ${externalCount} external agents in the front row.`
  );
}
