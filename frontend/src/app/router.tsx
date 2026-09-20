import { lazy } from "react";
import type { ComponentType } from "react";
import { Navigate, Outlet, createBrowserRouter, type RouteObject } from "react-router-dom";

import { PERMISSIONS } from "../auth/permissions";
import { ProtectedRoute } from "../auth/ProtectedRoute";
import { RequirePermission } from "../auth/PermissionGuard";
import { AppShell } from "../components/layout/AppShell";
import { LoginPage } from "../features/login/LoginPage";
import { AccessDeniedPage, FeatureUnavailablePage, NotFoundContent, NotFoundPage } from "../features/system/SystemPages";
import { RootRedirect } from "./RootRedirect";
import { RouteErrorPage } from "./RouteErrorPage";

/** Route-level code splitting for named page exports. */
function page<K extends string>(loader: () => Promise<Record<K, ComponentType>>, name: K) {
  return lazy(async () => ({ default: (await loader())[name] }));
}

const DashboardPage = page(() => import("../features/dashboard/DashboardPage"), "DashboardPage");
const MerchantsListPage = page(() => import("../features/merchants/MerchantsListPage"), "MerchantsListPage");
const MerchantCreatePage = page(() => import("../features/merchants/MerchantCreatePage"), "MerchantCreatePage");
const MerchantDetailPage = page(() => import("../features/merchants/MerchantDetailPage"), "MerchantDetailPage");
const UsersPage = page(() => import("../features/users/UsersPage"), "UsersPage");
const UserDetailPage = page(() => import("../features/users/UserDetailPage"), "UserDetailPage");
const RolesPage = page(() => import("../features/roles/RolesPage"), "RolesPage");
const RoleDetailPage = page(() => import("../features/roles/RoleDetailPage"), "RoleDetailPage");
const PermissionsPage = page(() => import("../features/permissions/PermissionsPage"), "PermissionsPage");
const AuditLogsPage = page(() => import("../features/audit-logs/AuditLogsPage"), "AuditLogsPage");
const ProfilePage = page(() => import("../features/profile/ProfilePage"), "ProfilePage");
const MerchantDashboardPage = page(
  () => import("../features/merchant-dashboard/MerchantDashboardPage"),
  "MerchantDashboardPage"
);
const DeliveryTeamListPage = page(() => import("../features/delivery-team/DeliveryTeamListPage"), "DeliveryTeamListPage");
const DeliveryMemberCreatePage = page(
  () => import("../features/delivery-team/DeliveryMemberCreatePage"),
  "DeliveryMemberCreatePage"
);
const DeliveryMemberDetailPage = page(
  () => import("../features/delivery-team/DeliveryMemberDetailPage"),
  "DeliveryMemberDetailPage"
);

function guarded(permission: string | readonly string[], element: JSX.Element) {
  return <RequirePermission permission={permission}>{element}</RequirePermission>;
}

export const routes: RouteObject[] = [
  {
    element: <Outlet />,
    errorElement: <RouteErrorPage />,
    children: [
      { path: "/", element: <RootRedirect /> },
      { path: "/login", element: <LoginPage /> },
      { path: "/access-denied", element: <AccessDeniedPage /> },
      {
        path: "/admin",
        element: (
          <ProtectedRoute channel="admin">
            <AppShell channel="admin" />
          </ProtectedRoute>
        ),
        children: [
          { index: true, element: <Navigate to="dashboard" replace /> },
          { path: "dashboard", element: guarded(PERMISSIONS.dashboardView, <DashboardPage />) },
          { path: "merchants", element: guarded(PERMISSIONS.merchantsView, <MerchantsListPage />) },
          {
            path: "merchants/new",
            element: guarded([PERMISSIONS.merchantsCreate], <MerchantCreatePage />)
          },
          { path: "merchants/:merchantId", element: guarded(PERMISSIONS.merchantsView, <MerchantDetailPage />) },
          { path: "customers", element: <FeatureUnavailablePage feature="admin-customers" /> },
          { path: "users", element: guarded(PERMISSIONS.usersView, <UsersPage />) },
          { path: "users/:userId", element: guarded(PERMISSIONS.usersView, <UserDetailPage />) },
          { path: "roles", element: guarded(PERMISSIONS.rolesView, <RolesPage />) },
          { path: "roles/:roleId", element: guarded(PERMISSIONS.rolesView, <RoleDetailPage />) },
          { path: "permissions", element: guarded(PERMISSIONS.permissionsView, <PermissionsPage />) },
          { path: "audit-logs", element: guarded(PERMISSIONS.auditLogsView, <AuditLogsPage />) },
          { path: "profile", element: <ProfilePage /> },
          { path: "*", element: <NotFoundContent /> }
        ]
      },
      {
        path: "/merchant",
        element: (
          <ProtectedRoute channel="merchant">
            <AppShell channel="merchant" />
          </ProtectedRoute>
        ),
        children: [
          { index: true, element: <Navigate to="dashboard" replace /> },
          { path: "dashboard", element: <MerchantDashboardPage /> },
          {
            path: "delivery-team",
            element: guarded(PERMISSIONS.deliveryUsersView, <DeliveryTeamListPage />)
          },
          {
            path: "delivery-team/new",
            element: guarded(PERMISSIONS.deliveryUsersCreate, <DeliveryMemberCreatePage />)
          },
          {
            path: "delivery-team/:memberId",
            element: guarded(PERMISSIONS.deliveryUsersView, <DeliveryMemberDetailPage />)
          },
          { path: "customers", element: <FeatureUnavailablePage feature="merchant-customers" /> },
          { path: "orders", element: <FeatureUnavailablePage feature="merchant-orders" /> },
          { path: "inventory", element: <FeatureUnavailablePage feature="merchant-inventory" /> },
          { path: "payments", element: <FeatureUnavailablePage feature="merchant-payments" /> },
          { path: "reports", element: <FeatureUnavailablePage feature="merchant-reports" /> },
          { path: "profile", element: <ProfilePage /> },
          { path: "*", element: <NotFoundContent /> }
        ]
      },
      { path: "*", element: <NotFoundPage /> }
    ]
  }
];

export function createAppRouter() {
  return createBrowserRouter(routes, {
    future: {
      v7_relativeSplatPath: true,
      v7_fetcherPersist: true,
      v7_normalizeFormMethod: true,
      v7_partialHydration: true,
      v7_skipActionErrorRevalidation: true
    }
  });
}
