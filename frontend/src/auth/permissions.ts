import type { AuthChannel } from "./token-storage";

/** Permission codes enforced by the backend (see backend/app/modules/roles/seeds.py). */
export const PERMISSIONS = {
  dashboardView: "dashboard.view",
  merchantsView: "merchants.view",
  merchantsCreate: "merchants.create",
  merchantsUpdate: "merchants.update",
  merchantsActivate: "merchants.activate",
  merchantsBlock: "merchants.block",
  merchantUsersView: "merchant_users.view",
  merchantUsersCreate: "merchant_users.create",
  merchantUsersUpdate: "merchant_users.update",
  usersView: "users.view",
  usersCreate: "users.create",
  usersUpdate: "users.update",
  usersActivate: "users.activate",
  usersBlock: "users.block",
  usersViewPermissions: "users.view_permissions",
  usersRevokeSessions: "users.revoke_sessions",
  usersAssignRoles: "users.assign_roles",
  usersRemoveRoles: "users.remove_roles",
  rolesView: "roles.view",
  rolesCreate: "roles.create",
  rolesUpdate: "roles.update",
  rolesDelete: "roles.delete",
  rolesActivate: "roles.activate",
  rolesAssignPermissions: "roles.assign_permissions",
  rolesAssignChannels: "roles.assign_channels",
  permissionsView: "permissions.view",
  auditLogsView: "audit_logs.view",
  deliveryUsersView: "delivery_users.view",
  deliveryUsersCreate: "delivery_users.create",
  deliveryUsersUpdate: "delivery_users.update",
  deliveryUsersActivate: "delivery_users.activate",
  deliveryUsersBlock: "delivery_users.block"
} as const;

export type PermissionCode = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];

export function hasPermission(granted: readonly string[] | undefined, required: string | readonly string[]): boolean {
  if (!granted) return false;
  const list = typeof required === "string" ? [required] : required;
  return list.every((permission) => granted.includes(permission));
}

export function hasAnyPermission(granted: readonly string[] | undefined, required: readonly string[]): boolean {
  if (!granted) return false;
  return required.some((permission) => granted.includes(permission));
}

export const CHANNEL_HOME: Record<AuthChannel, string> = {
  admin: "/admin/dashboard",
  merchant: "/merchant/dashboard"
};

/**
 * Only same-origin, in-panel paths for the signed-in channel are accepted as a post-login
 * destination; anything else falls back to the channel home.
 */
export function safeRedirectPath(candidate: unknown, channel: AuthChannel): string {
  if (typeof candidate !== "string") return CHANNEL_HOME[channel];
  if (!candidate.startsWith("/") || candidate.startsWith("//") || candidate.includes("\\")) {
    return CHANNEL_HOME[channel];
  }
  const prefix = `/${channel}`;
  if (candidate !== prefix && !candidate.startsWith(`${prefix}/`)) return CHANNEL_HOME[channel];
  return candidate;
}
