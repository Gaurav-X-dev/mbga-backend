import { PERMISSIONS } from "../auth/permissions";
import type { AuthChannel } from "../auth/token-storage";
import type { IconName } from "../components/common/Icon";

export type NavItem = {
  to: string;
  label: string;
  icon: IconName;
  /** All listed permissions are required. Omit for items every panel user can open. */
  permissions?: string[];
  /** Module has no backend API yet; shown with a "Soon" tag and an explanatory page. */
  unavailable?: boolean;
};

export type NavSection = { title: string; items: NavItem[] };

export const NAVIGATION: Record<AuthChannel, NavSection[]> = {
  admin: [
    {
      title: "Workspace",
      items: [{ to: "/admin/dashboard", label: "Dashboard", icon: "dashboard", permissions: [PERMISSIONS.dashboardView] }]
    },
    {
      title: "Business Operations",
      items: [
        { to: "/admin/merchants", label: "Merchant Network", icon: "store", permissions: [PERMISSIONS.merchantsView] },
        { to: "/admin/orders", label: "Orders", icon: "cart", permissions: [PERMISSIONS.ordersView] },
        { to: "/admin/deliveries", label: "Deliveries", icon: "truck", permissions: [PERMISSIONS.deliveryView] },
        { to: "/admin/delivery-users", label: "Delivery drivers", icon: "userCheck", permissions: [PERMISSIONS.deliveryUsersView] },
        { to: "/admin/live-location", label: "Live Location Tracking", icon: "mapPin", permissions: [PERMISSIONS.merchantsView, PERMISSIONS.deliveryUsersView] },
        { to: "/admin/vehicles", label: "Vehicles", icon: "truck", permissions: [PERMISSIONS.deliveryView] },
        { to: "/admin/inventory", label: "Inventory", icon: "box", permissions: [PERMISSIONS.inventoryView] },
        { to: "/admin/pricing", label: "Pricing", icon: "trendingUp", permissions: [PERMISSIONS.pricingView] },
        { to: "/admin/payments", label: "Payments", icon: "wallet", permissions: [PERMISSIONS.paymentsView] },
        { to: "/admin/payments?view=invoices", label: "Invoices", icon: "fileText", permissions: [PERMISSIONS.paymentsView] },
        { to: "/admin/credit", label: "Credit control", icon: "shield", permissions: [PERMISSIONS.creditView] },
        { to: "/admin/expenses", label: "Expenses", icon: "fileText", permissions: [PERMISSIONS.expensesView] },
        { to: "/admin/tasks", label: "Tasks", icon: "checkCircle", permissions: [PERMISSIONS.tasksView] },
        { to: "/admin/reports", label: "Reports", icon: "chart", permissions: [PERMISSIONS.reportsView] },
        { to: "/admin/customer-accounts", label: "Customers", icon: "users", permissions: [PERMISSIONS.customersView] },
        { to: "/admin/customers", label: "Customer KYC", icon: "idCard", permissions: [PERMISSIONS.customersReview] },
        { to: "/admin/approvals", label: "Approvals", icon: "inbox", permissions: [PERMISSIONS.customersReview] }
      ]
    },
    {
      title: "IAM & Security",
      items: [
        { to: "/admin/users", label: "Team Users", icon: "users", permissions: [PERMISSIONS.usersView] },
        { to: "/admin/roles", label: "Roles & Access", icon: "shield", permissions: [PERMISSIONS.rolesView] },
        { to: "/admin/permissions", label: "Permission Matrix", icon: "key", permissions: [PERMISSIONS.permissionsView] },
        { to: "/admin/login-sessions", label: "Login Sessions", icon: "devices", permissions: [PERMISSIONS.usersRevokeSessions] },
        { to: "/admin/otp-logs", label: "OTP Logs", icon: "key", permissions: [PERMISSIONS.otpLogsView] },
        { to: "/admin/catalogue", label: "Business Catalogue", icon: "box", permissions: [PERMISSIONS.catalogueView] },
        { to: "/admin/app-settings", label: "App Settings", icon: "settings", permissions: [PERMISSIONS.platformSettingsView] },
        { to: "/admin/privacy-policy", label: "Privacy Policy", icon: "shield", permissions: [PERMISSIONS.platformSettingsView] },
        { to: "/admin/audit-logs", label: "Audit Trail", icon: "history", permissions: [PERMISSIONS.auditLogsView] }
      ]
    },
    // Developer section hidden for now; the /admin/api-console route still works if opened directly.
    // {
    //   title: "Developer",
    //   items: [{ to: "/admin/api-console", label: "API Console", icon: "code" }]
    // },
    {
      title: "Account",
      items: [{ to: "/admin/profile", label: "Profile Settings", icon: "settings" }]
    }
  ],
  merchant: [
    {
      title: "Workspace",
      items: [{ to: "/merchant/dashboard", label: "Dashboard", icon: "dashboard" }]
    },
    {
      title: "Business Operations",
      items: [
        { to: "/merchant/customers", label: "Customers", icon: "users" },
        { to: "/merchant/orders", label: "Orders", icon: "cart" },
        { to: "/merchant/deliveries", label: "Deliveries", icon: "truck" },
        {
          to: "/merchant/delivery-team",
          label: "Delivery team",
          icon: "userCheck",
          permissions: [PERMISSIONS.deliveryUsersView]
        },
        { to: "/merchant/vehicles", label: "Vehicles", icon: "truck" },
        { to: "/merchant/inventory", label: "Inventory", icon: "box" },
        { to: "/merchant/pricing", label: "Pricing", icon: "trendingUp" },
        { to: "/merchant/payments", label: "Payments", icon: "wallet" },
        { to: "/merchant/payments?view=invoices", label: "Invoices", icon: "fileText" },
        { to: "/merchant/credit", label: "Credit control", icon: "shield" },
        { to: "/merchant/expenses", label: "Expenses", icon: "fileText" },
        { to: "/merchant/tasks", label: "Tasks", icon: "checkCircle" },
        { to: "/merchant/reports", label: "Reports", icon: "chart" }
      ]
    },
    {
      title: "IAM & Security",
      items: [{ to: "/merchant/app-settings", label: "App Settings", icon: "settings", permissions: [PERMISSIONS.deliveryView] }]
    },
    {
      title: "Account",
      items: [{ to: "/merchant/profile", label: "Profile Settings", icon: "settings" }]
    }
  ]
};

export function visibleNavigation(channel: AuthChannel, permissions: readonly string[]): NavSection[] {
  return NAVIGATION[channel]
    .map((section) => ({
      ...section,
      items: section.items.filter((item) => (item.permissions ?? []).every((code) => permissions.includes(code)))
    }))
    .filter((section) => section.items.length > 0);
}

export const PANEL_LABEL: Record<AuthChannel, string> = {
  admin: "Admin panel",
  merchant: "Merchant panel"
};

export const PANEL_SUMMARY: Record<AuthChannel, string> = {
  admin: "Head Office Control Center",
  merchant: "Agency Operations Workspace"
};

/** Lists the top-bar search can jump into; each accepts `?search=` like its own search box. */
export type SearchTarget = { label: string; path: string; icon: IconName; permissions: string[] };

export const SEARCH_TARGETS: Record<AuthChannel, SearchTarget[]> = {
  admin: [
    { label: "Merchants", path: "/admin/merchants", icon: "store", permissions: [PERMISSIONS.merchantsView] },
    { label: "Team users", path: "/admin/users", icon: "users", permissions: [PERMISSIONS.usersView] },
    { label: "Roles", path: "/admin/roles", icon: "shield", permissions: [PERMISSIONS.rolesView] }
  ],
  merchant: [
    { label: "Delivery team", path: "/merchant/delivery-team", icon: "truck", permissions: [PERMISSIONS.deliveryUsersView] }
  ]
};

export const SEARCH_PLACEHOLDER: Record<AuthChannel, string> = {
  admin: "Search merchants, users, roles...",
  merchant: "Search delivery team..."
};

export type QuickAction = { label: string; to: string; icon: IconName; permissions: string[] };

export const QUICK_ACTIONS: Record<AuthChannel, QuickAction[]> = {
  admin: [
    { label: "Add merchant", to: "/admin/merchants/new", icon: "store", permissions: [PERMISSIONS.merchantsCreate] },
    { label: "Add team user", to: "/admin/users?create=1", icon: "userPlus", permissions: [PERMISSIONS.usersCreate] },
    { label: "Add role", to: "/admin/roles?create=1", icon: "shield", permissions: [PERMISSIONS.rolesCreate] }
  ],
  merchant: [
    {
      label: "Add delivery member",
      to: "/merchant/delivery-team/new",
      icon: "truck",
      permissions: [PERMISSIONS.deliveryUsersCreate]
    }
  ]
};


