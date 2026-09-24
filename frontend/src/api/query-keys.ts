import type { AuditLogListParams } from "./audit-logs.api";
import type { DeliveryMemberListParams } from "./delivery-team.api";
import type { MerchantListParams } from "./merchants.api";
import type { RoleListParams } from "./roles.api";
import type { UserListParams } from "./users.api";

/**
 * Query keys grouped by feature. Every key starts with the channel so that an Admin
 * cache entry can never be served to a Merchant session (the cache is also cleared on sign-out).
 */
export const queryKeys = {
  me: (channel: string) => ["auth", channel, "me"] as const,

  adminDashboard: {
    all: ["admin", "dashboard"] as const,
    summary: () => ["admin", "dashboard", "summary"] as const
  },

  merchants: {
    all: ["admin", "merchants"] as const,
    lists: () => ["admin", "merchants", "list"] as const,
    list: (params: MerchantListParams) => ["admin", "merchants", "list", params] as const,
    detail: (merchantId: string) => ["admin", "merchants", "detail", merchantId] as const,
    users: (merchantId: string) => ["admin", "merchants", "detail", merchantId, "users"] as const
  },

  users: {
    all: ["admin", "users"] as const,
    lists: () => ["admin", "users", "list"] as const,
    list: (params: UserListParams) => ["admin", "users", "list", params] as const,
    detail: (userId: string) => ["admin", "users", "detail", userId] as const,
    roles: (userId: string) => ["admin", "users", "detail", userId, "roles"] as const,
    permissions: (userId: string, channel: string) =>
      ["admin", "users", "detail", userId, "permissions", channel] as const,
    channels: (userId: string) => ["admin", "users", "detail", userId, "channels"] as const
  },

  roles: {
    all: ["admin", "roles"] as const,
    lists: () => ["admin", "roles", "list"] as const,
    list: (params: RoleListParams) => ["admin", "roles", "list", params] as const,
    detail: (roleId: string) => ["admin", "roles", "detail", roleId] as const,
    permissions: (roleId: string) => ["admin", "roles", "detail", roleId, "permissions"] as const,
    channels: (roleId: string) => ["admin", "roles", "detail", roleId, "channels"] as const,
    users: (roleId: string) => ["admin", "roles", "detail", roleId, "users"] as const
  },

  permissions: {
    grouped: () => ["admin", "permissions", "grouped"] as const
  },

  auditLogs: {
    all: ["admin", "audit-logs"] as const,
    list: (params: AuditLogListParams) => ["admin", "audit-logs", "list", params] as const,
    detail: (auditLogId: string) => ["admin", "audit-logs", "detail", auditLogId] as const
  },

  deliveryTeam: {
    all: ["merchant", "delivery-team"] as const,
    lists: () => ["merchant", "delivery-team", "list"] as const,
    list: (params: DeliveryMemberListParams) => ["merchant", "delivery-team", "list", params] as const,
    detail: (memberId: string) => ["merchant", "delivery-team", "detail", memberId] as const
  }
};
