import { useMemo } from "react";

import type { AgentRoom, ProjectSummary } from "@/types/api";

import { HALL_KEY } from "./buildings";
import { assignLots } from "./lots";
import { LOT_COUNT } from "./town";
import { RESIDENCE_KEY } from "./townScene";

interface TownDirectoryProps {
  projects: readonly ProjectSummary[];
  rooms: readonly AgentRoom[];
  focusKey: string | null;
  onFocus: (key: string | null) => void;
}

/** The HTML side of the town. The canvas shows a project's code only; this panel may show
 * the name as well (operator decision O17), plus the allow-listed agent fields P1 already
 * puts on this page: display name and activity. Nothing else from the API reaches it. */
export function TownDirectory({ projects, rooms, focusKey, onFocus }: TownDirectoryProps) {
  // The scene places projects with the same function, so the same ones get no building.
  const lots = useMemo(() => assignLots(projects.map((p) => p.id)), [projects]);
  return (
    <aside className="card" aria-label="Town directory" style={{ flex: "1 1 15rem", minWidth: 0 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
        <strong>Town</strong>
        {/* aria-disabled, not disabled: activating it must not drop keyboard focus to <body>. */}
        <button
          type="button"
          aria-disabled={focusKey === null}
          style={focusKey === null ? { opacity: 0.5, cursor: "default" } : undefined}
          onClick={() => {
            if (focusKey !== null) onFocus(null);
          }}
        >
          Back to overview
        </button>
      </div>

      <ul style={{ listStyle: "none", padding: 0, margin: "0.75rem 0 0", display: "grid", gap: "0.5rem" }}>
        <li>
          <button type="button" aria-current={focusKey === RESIDENCE_KEY ? "true" : undefined} onClick={() => onFocus(RESIDENCE_KEY)}>
            Residence
          </button>
          <div style={{ color: "var(--text-muted)", fontSize: "0.85em" }}>Every twin's room; idle twins live here</div>
        </li>
        <li>
          <button type="button" aria-current={focusKey === HALL_KEY ? "true" : undefined} onClick={() => onFocus(HALL_KEY)}>
            Community hall
          </button>
          <div style={{ color: "var(--text-muted)", fontSize: "0.85em" }}>Shared services, work with no project</div>
        </li>
        {projects.map((project) => (
          <ProjectEntry
            key={project.id}
            project={project}
            rooms={rooms}
            focused={focusKey === project.id}
            hasBuilding={lots.has(project.id)}
            onFocus={onFocus}
          />
        ))}
      </ul>
      {projects.length === 0 && (
        <p style={{ color: "var(--text-muted)" }}>No projects yet. Each project becomes a building here.</p>
      )}
    </aside>
  );
}

interface ProjectEntryProps {
  project: ProjectSummary;
  rooms: readonly AgentRoom[];
  focused: boolean;
  hasBuilding: boolean;
  onFocus: (key: string) => void;
}

function ProjectEntry({ project, rooms, focused, hasBuilding, onFocus }: ProjectEntryProps) {
  const assigned = rooms.filter((room) => room.project_id === project.id);
  return (
    <li>
      <button type="button" aria-current={focused ? "true" : undefined} disabled={!hasBuilding} onClick={() => onFocus(project.id)}>
        {project.code}
      </button>{" "}
      <span className={`badge status-${project.status}`}>{project.status}</span>
      <div>{project.name}</div>
      {!hasBuilding && (
        <div style={{ color: "var(--text-muted)", fontSize: "0.85em" }}>
          No building: all {LOT_COUNT} lots are in use.
        </div>
      )}
      {assigned.length > 0 && (
        <div style={{ color: "var(--text-muted)", fontSize: "0.85em" }}>
          {assigned.map((room) => `${room.display_name} (${room.activity})`).join(", ")}
        </div>
      )}
    </li>
  );
}
