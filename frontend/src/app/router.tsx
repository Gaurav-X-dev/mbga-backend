import { createBrowserRouter } from "react-router-dom";

import { ShellLayout } from "../layouts/ShellLayout";
import { ProtectedRoute } from "../auth/ProtectedRoute";
import { AuditLogsPage } from "../features/audit-logs/AuditLogsPage";
import { DashboardPage } from "../features/dashboard/DashboardPage";
import { LoginPage } from "../features/login/LoginPage";
import { PermissionsPage } from "../features/permissions/PermissionsPage";
import { RolesPage } from "../features/roles/RolesPage";
import { UsersPage } from "../features/users/UsersPage";

export const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    path: "/",
    element: (
      <ProtectedRoute>
        <ShellLayout />
      </ProtectedRoute>
    ),
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "users", element: <UsersPage /> },
      { path: "roles", element: <RolesPage /> },
      { path: "permissions", element: <PermissionsPage /> },
      { path: "audit-logs", element: <AuditLogsPage /> }
    ]
  }
]);
