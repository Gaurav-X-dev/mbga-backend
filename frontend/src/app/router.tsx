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
function page<K extends string>(loader: () => Promise<Record<K, ComponentType<any>>>, name: K) {
  return lazy(async () => ({ default: (await loader())[name] }));
}

const PrivacyPolicyAdminPage = page(() => import("../features/legal-pages/PrivacyPolicyAdminPage"), "PrivacyPolicyAdminPage");

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
const CustomerKycPage = page(() => import("../features/customers/CustomerKycPage"), "CustomerKycPage");
const CustomerKycDetailPage = page(
  () => import("../features/customers/CustomerKycDetailPage"),
  "CustomerKycDetailPage"
);
const ApprovalsPage = page(() => import("../features/approvals/ApprovalsPage"), "ApprovalsPage");
const ApiExplorerPage = page(() => import("../features/api-explorer/ApiExplorerPage"), "ApiExplorerPage");
const OtpLogsPage = page(() => import("../features/otp-logs/OtpLogsPage"), "OtpLogsPage");
const AdminCataloguePage = page(() => import("../features/admin-catalogue/AdminCataloguePage"), "AdminCataloguePage");
const LoginSessionsPage = page(() => import("../features/sessions/LoginSessionsPage"), "LoginSessionsPage");
const AppSettingsPage = page(() => import("../features/app-settings/AppSettingsPage"), "AppSettingsPage");
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
const MerchantCustomersPage = page(() => import("../features/merchant-customers/MerchantCustomersPage"), "MerchantCustomersPage");
const MerchantOrdersPage = page(() => import("../features/merchant-orders/MerchantOrdersPage"), "MerchantOrdersPage");
const MerchantInventoryPage = page(() => import("../features/merchant-inventory/MerchantInventoryPage"), "MerchantInventoryPage");
const MerchantPaymentsPage = page(() => import("../features/merchant-payments/MerchantPaymentsPage"), "MerchantPaymentsPage");
const MerchantReportsPage = page(() => import("../features/merchant-reports/MerchantReportsPage"), "MerchantReportsPage");

const AdminOrdersPage = page(() => import("../features/admin-orders/AdminOrdersPage"), "AdminOrdersPage");
const AdminInventoryPage = page(() => import("../features/admin-inventory/AdminInventoryPage"), "AdminInventoryPage");
const AdminExpensesPage = page(() => import("../features/admin-expenses/AdminExpensesPage"), "AdminExpensesPage");
const AdminTasksPage = page(() => import("../features/admin-tasks/AdminTasksPage"), "AdminTasksPage");
const AdminTaskDetailPage = page(() => import("../features/admin-tasks/AdminTaskDetailPage"), "AdminTaskDetailPage");
const AdminDeliveriesPage = page(() => import("../features/admin-deliveries/AdminDeliveriesPage"), "AdminDeliveriesPage");
const AdminCustomersPage = page(() => import("../features/admin-customers/AdminCustomersPage"), "AdminCustomersPage");
const AdminCustomerDetailPage = page(() => import("../features/admin-customers/AdminCustomerDetailPage"), "AdminCustomerDetailPage");
const LiveLocationPage = page(() => import("../features/live-location/LiveLocationPage"), "LiveLocationPage");
const AdminDeliveryUsersPage = page(() => import("../features/admin-delivery-users/AdminDeliveryUsersPage"), "AdminDeliveryUsersPage");
const AdminPricingPage = page(() => import("../features/admin-pricing/AdminPricingPage"), "AdminPricingPage");
const AdminVehiclesPage = page(() => import("../features/admin-vehicles/AdminVehiclesPage"), "AdminVehiclesPage");
const AdminCreditPage = page(() => import("../features/admin-credit/AdminCreditPage"), "AdminCreditPage");
const AdminPaymentsPage = page(() => import("../features/admin-payments/AdminPaymentsPage"), "AdminPaymentsPage");
const AdminReportsPage = page(() => import("../features/admin-reports/AdminReportsPage"), "AdminReportsPage");

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
          { path: "orders", element: guarded(PERMISSIONS.ordersView, <AdminOrdersPage />) },
          { path: "inventory", element: guarded(PERMISSIONS.inventoryView, <AdminInventoryPage />) },
          { path: "deliveries", element: <AdminDeliveriesPage /> },
          { path: "delivery-users", element: guarded(PERMISSIONS.deliveryUsersView, <AdminDeliveryUsersPage />) },
          { path: "live-location", element: guarded([PERMISSIONS.merchantsView, PERMISSIONS.deliveryUsersView], <LiveLocationPage />) },
          { path: "vehicles", element: <AdminVehiclesPage /> },
          { path: "pricing", element: <AdminPricingPage /> },
          { path: "payments", element: guarded(PERMISSIONS.paymentsView, <AdminPaymentsPage />) },
          { path: "credit", element: guarded(PERMISSIONS.creditView, <AdminCreditPage />) },
          { path: "expenses", element: <AdminExpensesPage /> },
          { path: "tasks", element: <AdminTasksPage /> },
          { path: "tasks/:taskId", element: <AdminTaskDetailPage /> },
          { path: "reports", element: guarded(PERMISSIONS.reportsView, <AdminReportsPage />) },
          { path: "customer-accounts", element: <AdminCustomersPage /> },
          { path: "customer-accounts/:customerId", element: <AdminCustomerDetailPage /> },
          { path: "customers", element: <CustomerKycPage /> },
          { path: "customers/:applicationId", element: <CustomerKycDetailPage /> },
          { path: "approvals", element: <ApprovalsPage /> },
          { path: "users", element: guarded(PERMISSIONS.usersView, <UsersPage />) },
          { path: "users/:userId", element: guarded(PERMISSIONS.usersView, <UserDetailPage />) },
          { path: "roles", element: guarded(PERMISSIONS.rolesView, <RolesPage />) },
          { path: "roles/:roleId", element: guarded(PERMISSIONS.rolesView, <RoleDetailPage />) },
          { path: "permissions", element: guarded(PERMISSIONS.permissionsView, <PermissionsPage />) },
          { path: "login-sessions", element: guarded(PERMISSIONS.usersRevokeSessions, <LoginSessionsPage />) },
          { path: "otp-logs", element: <OtpLogsPage /> },
          { path: "catalogue", element: <AdminCataloguePage /> },
          { path: "audit-logs", element: guarded(PERMISSIONS.auditLogsView, <AuditLogsPage />) },
          { path: "app-settings", element: guarded(PERMISSIONS.platformSettingsView, <AppSettingsPage />) },
          { path: "privacy-policy", element: guarded(PERMISSIONS.platformSettingsView, <PrivacyPolicyAdminPage />) },
          { path: "profile", element: <ProfilePage /> },
          { path: "api-console", element: <ApiExplorerPage /> },
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
          { path: "customers", element: <MerchantCustomersPage /> },
          { path: "customers/:customerId", element: <AdminCustomerDetailPage /> },
          { path: "orders", element: <MerchantOrdersPage /> },
          { path: "deliveries", element: <AdminDeliveriesPage isMerchantPanel /> },
          { path: "vehicles", element: <AdminVehiclesPage isMerchantPanel /> },
          { path: "inventory", element: <MerchantInventoryPage /> },
          { path: "pricing", element: <AdminPricingPage isMerchantPanel /> },
          { path: "payments", element: <MerchantPaymentsPage /> },
          { path: "credit", element: <AdminCreditPage isMerchantPanel /> },
          { path: "expenses", element: <AdminExpensesPage isMerchantPanel /> },
          { path: "tasks", element: <AdminTasksPage isMerchantPanel /> },
          { path: "tasks/:taskId", element: <AdminTaskDetailPage /> },
          { path: "reports", element: <MerchantReportsPage /> },
          { path: "app-settings", element: guarded(PERMISSIONS.deliveryView, <AppSettingsPage />) },
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




