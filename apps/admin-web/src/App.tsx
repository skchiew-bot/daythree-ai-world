import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "@/components/Layout";
import { useAuth } from "@/lib/auth";
import { AgentRegistry } from "@/pages/AgentRegistry";
import { CreateAgent } from "@/pages/CreateAgent";
import { Dashboard } from "@/pages/Dashboard";
import { Login } from "@/pages/Login";
import { MissionControl } from "@/pages/MissionControl";
import { MissionDetail } from "@/pages/MissionDetail";
import { World } from "@/pages/World";

export default function App() {
  const { isAuthenticated, isLoading } = useAuth();

  if (!isAuthenticated) {
    if (isLoading) return <p style={{ padding: "2rem" }}>Loading…</p>;
    return <Login />;
  }

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/agents" element={<AgentRegistry />} />
        <Route path="/agents/new" element={<CreateAgent />} />
        <Route path="/missions" element={<MissionControl />} />
        <Route path="/missions/:missionId" element={<MissionDetail />} />
        <Route path="/world" element={<World />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
