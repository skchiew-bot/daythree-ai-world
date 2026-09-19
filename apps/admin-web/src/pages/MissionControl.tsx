import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { z } from "zod";

import { ApiError } from "@/api/client";
import { useAgents, useCancelMission, useCreateMission, useMissions, useProjects, useStartMission } from "@/api/hooks";

const schema = z.object({
  title: z.string().min(1, "Required"),
  objective: z.string().min(1, "Required"),
  assigned_agent_id: z.string().min(1, "Select an agent"),
  priority: z.enum(["low", "normal", "high", "urgent"]),
  risk_level: z.enum(["low", "medium", "high"]),
  project_id: z.string().optional(),
});
type FormValues = z.infer<typeof schema>;

export function MissionControl() {
  const { data: missions, isLoading } = useMissions();
  const { data: agents } = useAgents();
  const { data: projects } = useProjects();
  const createMission = useCreateMission();
  const startMission = useStartMission();
  const cancelMission = useCancelMission();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { priority: "normal", risk_level: "low" },
  });

  async function onSubmit(values: FormValues) {
    setSubmitError(null);
    try {
      await createMission.mutateAsync({ ...values, project_id: values.project_id || null });
      reset();
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Failed to create mission.");
    }
  }

  return (
    <div>
      <h2>Mission Control</h2>

      <form className="card" onSubmit={handleSubmit(onSubmit)}>
        <h3 style={{ marginTop: 0 }}>New mission</h3>
        <div className="form-field">
          <label htmlFor="title">Title</label>
          <input id="title" {...register("title")} />
          {errors.title && <span className="form-error">{errors.title.message}</span>}
        </div>
        <div className="form-field">
          <label htmlFor="objective">Objective</label>
          <textarea id="objective" rows={3} {...register("objective")} />
          {errors.objective && <span className="form-error">{errors.objective.message}</span>}
        </div>
        <div className="form-field">
          <label htmlFor="assigned_agent_id">Assigned agent</label>
          <select id="assigned_agent_id" {...register("assigned_agent_id")}>
            <option value="">Select…</option>
            {agents?.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.display_name} ({agent.agent_code})
              </option>
            ))}
          </select>
          {errors.assigned_agent_id && <span className="form-error">{errors.assigned_agent_id.message}</span>}
        </div>
        <div className="form-field">
          <label htmlFor="project_id">Project (optional)</label>
          <select id="project_id" {...register("project_id")}>
            <option value="">No project — community hall</option>
            {projects
              ?.filter((p) => p.status === "active")
              .map((project) => (
                <option key={project.id} value={project.id}>
                  {project.code} — {project.name}
                </option>
              ))}
          </select>
        </div>
        <div style={{ display: "flex", gap: "1rem" }}>
          <div className="form-field" style={{ flex: 1 }}>
            <label htmlFor="priority">Priority</label>
            <select id="priority" {...register("priority")}>
              <option value="low">low</option>
              <option value="normal">normal</option>
              <option value="high">high</option>
              <option value="urgent">urgent</option>
            </select>
          </div>
          <div className="form-field" style={{ flex: 1 }}>
            <label htmlFor="risk_level">Risk level</label>
            <select id="risk_level" {...register("risk_level")}>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
          </div>
        </div>
        {submitError && <p className="form-error">{submitError}</p>}
        <button className="btn" type="submit" disabled={createMission.isPending}>
          {createMission.isPending ? "Creating…" : "Create mission"}
        </button>
      </form>

      <h3>Missions</h3>
      {isLoading && <p>Loading…</p>}
      <table>
        <thead>
          <tr>
            <th>Code</th>
            <th>Title</th>
            <th>Status</th>
            <th>Priority</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {missions?.map((mission) => (
            <tr key={mission.id}>
              <td>
                <Link to={`/missions/${mission.id}`}>{mission.mission_code}</Link>
              </td>
              <td>{mission.title}</td>
              <td>
                <span className={`badge status-${mission.status}`}>{mission.status}</span>
              </td>
              <td>{mission.priority}</td>
              <td style={{ display: "flex", gap: "0.4rem" }}>
                {(mission.status === "draft" || mission.status === "ready") && (
                  <button
                    className="btn secondary"
                    onClick={() => startMission.mutate(mission.id)}
                    disabled={startMission.isPending}
                  >
                    Start
                  </button>
                )}
                {mission.status === "running" && (
                  <button
                    className="btn danger"
                    onClick={() => cancelMission.mutate(mission.id)}
                    disabled={cancelMission.isPending}
                  >
                    Cancel
                  </button>
                )}
              </td>
            </tr>
          ))}
          {missions?.length === 0 && (
            <tr>
              <td colSpan={5} style={{ color: "var(--text-muted)" }}>
                No missions yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
