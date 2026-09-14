import { useDashboardSummary } from "@/api/hooks";

export function Dashboard() {
  const { data, isLoading, isError } = useDashboardSummary();

  if (isLoading) return <p>Loading dashboard…</p>;
  if (isError || !data) return <p className="form-error">Could not load dashboard summary.</p>;

  const stats: Array<{ label: string; value: string | number }> = [
    { label: "Total agents", value: data.total_agents },
    { label: "Active missions", value: data.active_missions },
    { label: "Completed missions", value: data.completed_missions },
    { label: "Failed missions", value: data.failed_missions },
    { label: "Model calls", value: data.model_calls },
    { label: "Current cost (USD)", value: `$${data.current_cost_usd.toFixed(4)}` },
  ];

  return (
    <div>
      <h2>Dashboard</h2>
      <div className="card-grid">
        {stats.map((stat) => (
          <div className="card" key={stat.label}>
            <div className="stat">{stat.value}</div>
            <div className="stat-label">{stat.label}</div>
          </div>
        ))}
      </div>
      <div className="card">
        <span className="stat-label">System status</span>
        <div>
          <span className={`badge status-${data.system_status === "ok" ? "active" : "failed"}`}>
            {data.system_status}
          </span>
        </div>
      </div>
    </div>
  );
}
