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
      title: "Overview",
      items: [{ to: "/admin/dashboard", label: "Dashboard", icon: "dashboard", permissions: [PERMISSIONS.dashboardView] }]
    },
    {
      title: "Business",
      items: [
        { to: "/admin/merchants", label: "Merchants", icon: "store", permissions: [PERMISSIONS.merchantsView] },
        { to: "/admin/customers", label: "Customers", icon: "idCard", unavailable: true }
      ]
    },
    {
      title: "Access and security",
      items: [
        { to: "/admin/users", label: "Users", icon: "users", permissions: [PERMISSIONS.usersView] },
        { to: "/admin/roles", label: "Roles", icon: "shield", permissions: [PERMISSIONS.rolesView] },
        { to: "/admin/permissions", label: "Permissions", icon: "key", permissions: [PERMISSIONS.permissionsView] },
        { to: "/admin/audit-logs", label: "Audit logs", icon: "history", permissions: [PERMISSIONS.auditLogsView] }
      ]
    },
    {
      title: "Account",
      items: [{ to: "/admin/profile", label: "My account", icon: "user" }]
    }
  ],
  merchant: [
    {
      title: "Overview",
      items: [{ to: "/merchant/dashboard", label: "Dashboard", icon: "dashboard" }]
    },
    {
      title: "Operations",
      items: [
        {
          to: "/merchant/delivery-team",
          label: "Delivery team",
          icon: "truck",
          permissions: [PERMISSIONS.deliveryUsersView]
        }
      ]
    },
    {
      title: "Coming soon",
      items: [
        { to: "/merchant/customers", label: "Customers", icon: "idCard", unavailable: true },
        { to: "/merchant/orders", label: "Orders", icon: "cart", unavailable: true },
        { to: "/merchant/inventory", label: "Inventory", icon: "box", unavailable: true },
        { to: "/merchant/payments", label: "Payments", icon: "wallet", unavailable: true },
        { to: "/merchant/reports", label: "Reports", icon: "chart", unavailable: true }
      ]
    },
    {
      title: "Account",
      items: [{ to: "/merchant/profile", label: "My account", icon: "user" }]
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
