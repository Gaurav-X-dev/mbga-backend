import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";

const links = [
  { to: "/", label: "Dashboard", permission: "dashboard.view" },
  { to: "/users", label: "Users", permission: "users.view" },
  { to: "/roles", label: "Roles", permission: "roles.view" },
  { to: "/permissions", label: "Permissions", permission: "permissions.view" },
  { to: "/audit-logs", label: "Audit Logs", permission: "audit_logs.view" }
];

export function ShellLayout() {
  const auth = useAuth();
  const permissions = auth.user?.effective_permissions ?? [];
  const visibleLinks = links.filter((link) => permissions.includes(link.permission));
  return (
    <div className="shell">
      <aside className="sidebar" aria-label="Admin navigation">
        <strong>MBGA Admin</strong>
        <nav>
          {visibleLinks.map((link) => (
            <NavLink key={link.to} to={link.to}>
              {link.label}
            </NavLink>
          ))}
        </nav>
        <button type="button" className="logout" onClick={() => void auth.signOut()}>
          Logout
        </button>
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
