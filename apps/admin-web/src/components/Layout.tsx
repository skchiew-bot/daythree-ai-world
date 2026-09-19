import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "@/lib/auth";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/agents", label: "Agent Registry" },
  { to: "/agents/new", label: "Create Agent" },
  { to: "/missions", label: "Mission Control" },
  { to: "/projects", label: "Projects" },
  { to: "/world", label: "3D World" },
];

export function Layout() {
  const { user, logout } = useAuth();

  return (
    <div className="app-shell">
      <nav className="app-nav">
        <h1>Daythree AI World</h1>
        {NAV_ITEMS.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end}>
            {item.label}
          </NavLink>
        ))}
        <div style={{ marginTop: "2rem", fontSize: "0.8rem", color: "var(--text-muted)" }}>
          {user?.display_name} ({user?.role})
          <div>
            <button className="btn secondary" style={{ marginTop: "0.5rem" }} onClick={logout}>
              Sign out
            </button>
          </div>
        </div>
      </nav>
      <main className="app-content">
        <Outlet />
      </main>
    </div>
  );
}
