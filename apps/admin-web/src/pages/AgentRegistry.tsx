import { Link } from "react-router-dom";

import { useActivateAgent, useAgents, useSuspendAgent } from "@/api/hooks";

export function AgentRegistry() {
  const { data: agents, isLoading, isError } = useAgents();
  const suspendAgent = useSuspendAgent();
  const activateAgent = useActivateAgent();

  if (isLoading) return <p>Loading agents…</p>;
  if (isError || !agents) return <p className="form-error">Could not load agents.</p>;

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2>Agent Registry</h2>
        <Link className="btn" to="/agents/new">
          + Create agent
        </Link>
      </div>
      <table>
        <thead>
          <tr>
            <th>Agent Code</th>
            <th>Name</th>
            <th>Role</th>
            <th>Department</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {agents.map((agent) => (
            <tr key={agent.id}>
              <td>{agent.agent_code}</td>
              <td>{agent.display_name}</td>
              <td>{agent.role_name ?? "—"}</td>
              <td>{agent.department ?? "—"}</td>
              <td>
                <span className={`badge status-${agent.lifecycle_state}`}>{agent.lifecycle_state}</span>
              </td>
              <td>
                {agent.lifecycle_state === "active" ? (
                  <button
                    className="btn secondary"
                    onClick={() => suspendAgent.mutate(agent.id)}
                    disabled={suspendAgent.isPending}
                  >
                    Suspend
                  </button>
                ) : (
                  agent.active_version_id && (
                    <button
                      className="btn secondary"
                      onClick={() =>
                        activateAgent.mutate({ agentId: agent.id, versionId: agent.active_version_id! })
                      }
                      disabled={activateAgent.isPending}
                    >
                      Activate
                    </button>
                  )
                )}
              </td>
            </tr>
          ))}
          {agents.length === 0 && (
            <tr>
              <td colSpan={6} style={{ color: "var(--text-muted)" }}>
                No agents yet — create one to get started.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
