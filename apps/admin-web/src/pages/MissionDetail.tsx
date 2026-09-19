import { useState } from "react";
import { useParams } from "react-router-dom";

import {
  useArtifactDownloadUrl,
  useMission,
  useMissionArtifacts,
  useMissionModelInvocations,
  useMissionTasks,
  useMissionTimeline,
  useProjects,
  useRetryTask,
} from "@/api/hooks";

const TABS = ["Overview", "Tasks", "Artifact", "Timeline", "Model Usage", "Audit"] as const;
type Tab = (typeof TABS)[number];

export function MissionDetail() {
  const { missionId } = useParams<{ missionId: string }>();
  const [tab, setTab] = useState<Tab>("Overview");

  const { data: mission } = useMission(missionId);
  const { data: projects } = useProjects();
  const { data: tasks } = useMissionTasks(missionId);
  const { data: artifacts } = useMissionArtifacts(missionId);
  const { data: timeline } = useMissionTimeline(missionId);
  const { data: invocations } = useMissionModelInvocations(missionId);
  const retryTask = useRetryTask();
  const downloadArtifact = useArtifactDownloadUrl();

  if (!mission) return <p>Loading mission…</p>;

  const project = projects?.find((p) => p.id === mission.project_id);

  return (
    <div>
      <h2>
        {mission.mission_code} — {mission.title}
      </h2>
      <span className={`badge status-${mission.status}`}>{mission.status}</span>

      <div className="tabs" style={{ marginTop: "1rem" }}>
        {TABS.map((t) => (
          <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>

      {tab === "Overview" && (
        <div className="card">
          <p>
            <strong>Objective:</strong> {mission.objective}
          </p>
          <p>
            <strong>Priority:</strong> {mission.priority} &nbsp; <strong>Risk:</strong> {mission.risk_level}
          </p>
          <p>
            <strong>Project:</strong> {project ? project.code : "— community hall"}
          </p>
          <p>
            <strong>Budget:</strong> ${mission.budget_policy.max_model_cost_usd} / {mission.budget_policy.max_model_calls}{" "}
            calls / {mission.budget_policy.max_runtime_minutes} min
          </p>
          <p>
            <strong>Created:</strong> {new Date(mission.created_at).toLocaleString()}
            {mission.started_at && (
              <>
                {" "}
                &nbsp; <strong>Started:</strong> {new Date(mission.started_at).toLocaleString()}
              </>
            )}
            {mission.completed_at && (
              <>
                {" "}
                &nbsp; <strong>Completed:</strong> {new Date(mission.completed_at).toLocaleString()}
              </>
            )}
          </p>
        </div>
      )}

      {tab === "Tasks" && (
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Status</th>
              <th>Retries</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {tasks?.map((task) => (
              <tr key={task.id}>
                <td>{task.title}</td>
                <td>
                  <span className={`badge status-${task.status}`}>{task.status}</span>
                </td>
                <td>{task.retry_count}</td>
                <td>
                  {task.status === "failed" && (
                    <button className="btn secondary" onClick={() => retryTask.mutate(task.id)}>
                      Retry
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "Artifact" && (
        <div>
          {artifacts?.map((artifact) => (
            <div className="card" key={artifact.id}>
              <p>
                <strong>{artifact.title}</strong> ({artifact.artifact_type}, v{artifact.version})
              </p>
              <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                sha256: {artifact.content_hash.slice(0, 16)}…
              </p>
              <button
                className="btn secondary"
                onClick={async () => {
                  const result = await downloadArtifact.mutateAsync(artifact.id);
                  window.open(result.download_url, "_blank");
                }}
              >
                Download (signed URL)
              </button>
            </div>
          ))}
          {artifacts?.length === 0 && <p style={{ color: "var(--text-muted)" }}>No artifact yet.</p>}
        </div>
      )}

      {tab === "Timeline" && (
        <ul>
          {timeline?.map((event) => (
            <li key={event.id}>
              <code>{new Date(event.occurred_at).toLocaleTimeString()}</code> — {event.event_type}
            </li>
          ))}
        </ul>
      )}

      {tab === "Model Usage" && (
        <table>
          <thead>
            <tr>
              <th>Provider</th>
              <th>Model</th>
              <th>Input tokens</th>
              <th>Output tokens</th>
              <th>Cost (USD)</th>
              <th>Latency (ms)</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {invocations?.map((inv) => (
              <tr key={inv.id}>
                <td>{inv.provider}</td>
                <td>{inv.model}</td>
                <td>{inv.input_tokens}</td>
                <td>{inv.output_tokens}</td>
                <td>{Number(inv.estimated_cost).toFixed(6)}</td>
                <td>{inv.latency_ms}</td>
                <td>{inv.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "Audit" && (
        <div>
          {timeline?.map((event) => (
            <div className="card" key={event.id}>
              <p>
                <strong>{event.event_type}</strong> — {new Date(event.occurred_at).toLocaleString()}
              </p>
              <p style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                actor: {event.actor_type} {event.actor_id ?? ""} · correlation: {event.correlation_id}
              </p>
              <pre className="json-view">{JSON.stringify(event.payload, null, 2)}</pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
