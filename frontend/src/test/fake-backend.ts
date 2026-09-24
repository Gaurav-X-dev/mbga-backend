import { AxiosError, AxiosHeaders, type AxiosAdapter, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";

import { apiClient } from "../api/client";

/**
 * In-memory stand-in for the MBGA backend, implementing the request/response
 * contracts from backend/docs/openapi-*.json for the flows the web panel uses.
 * Only used by Vitest integration tests.
 */

type Channel = "ADMIN" | "MERCHANT" | "DELIVERY";

type FakeUser = {
  id: string;
  mobile: string;
  name: string;
  status: string;
  channels: Partial<Record<Channel, string[]>>;
  roles: string[];
};

type Session = { userId: string; channel: Channel; revoked: boolean };

type FakeRole = { id: string; name: string; code: string; description: string | null; is_system: boolean; is_active: boolean };

export const OTP = "1234";

export const ADMIN_PERMISSIONS = [
  "dashboard.view",
  "merchants.view",
  "merchants.create",
  "merchants.update",
  "merchants.activate",
  "merchants.block",
  "merchant_users.view",
  "users.view",
  "users.create",
  "users.update",
  "users.activate",
  "users.block",
  "users.view_permissions",
  "users.revoke_sessions",
  "users.assign_roles",
  "users.remove_roles",
  "roles.view",
  "roles.create",
  "roles.update",
  "roles.activate",
  "roles.assign_permissions",
  "roles.assign_channels",
  "permissions.view",
  "audit_logs.view"
];

export const MANAGER_PERMISSIONS = [
  "delivery_users.view",
  "delivery_users.create",
  "delivery_users.update",
  "delivery_users.activate",
  "delivery_users.block"
];

export type FakeBackend = ReturnType<typeof createFakeBackend>;

export function createFakeBackend() {
  let counter = 0;
  const nextId = (prefix: string) => `${prefix}-${++counter}`;
  const users = new Map<string, FakeUser>();
  // `suppressed`: the number has no account, so (like the real backend) nothing is sent and no code works.
  const challenges = new Map<
    string,
    { mobile: string; channel: Channel; attempts: number; used: boolean; expired: boolean; suppressed?: boolean }
  >();
  const accessTokens = new Map<string, Session>();
  const refreshTokens = new Map<string, Session>();
  const merchants: Array<Record<string, unknown>> = [];
  const deliveryMembers: Array<Record<string, unknown> & { merchant_owner: string }> = [];
  const calls: string[] = [];
  const options = {
    failNetwork: false,
    forbidAll: false,
    /** Admin lists (users, roles, permissions, audit logs) return no rows. */
    emptyLists: false,
    /** Requests whose path starts with one of these return a 500 server error. */
    failPaths: [] as string[],
    /** Artificial response delay, to observe loading states. */
    delayMs: 0
  };
  const userStatus = new Map<string, string>();
  const roles: FakeRole[] = [
    { id: "role-super", name: "Super Admin", code: "super_admin", description: "System role: Super Admin", is_system: true, is_active: true },
    { id: "role-manager", name: "Manager", code: "manager", description: "System role: Manager", is_system: true, is_active: true },
    { id: "role-area", name: "Area Supervisor", code: "area_supervisor", description: "Oversees merchants in one area", is_system: false, is_active: true }
  ];
  const permissionGroups = [
    {
      module: "merchants",
      permissions: [
        { id: "perm-mv", name: "View merchant records", code: "merchants.view", module: "merchants", action: "view", description: "System permission: View merchant records", is_system: true, is_active: true },
        { id: "perm-mc", name: "Create merchant records", code: "merchants.create", module: "merchants", action: "create", description: null, is_system: true, is_active: true }
      ]
    },
    {
      module: "audit_logs",
      permissions: [
        { id: "perm-al", name: "View audit logs", code: "audit_logs.view", module: "audit_logs", action: "view", description: "Includes sign-in history", is_system: true, is_active: true }
      ]
    }
  ];
  const auditLogs = [
    { id: "log-2", event_type: "merchant.created", actor_user_id: "user-1", entity_type: "merchant", entity_id: "merchant-x", message: "Merchant created", created_at: "2026-09-16T08:30:00Z" },
    { id: "log-1", event_type: "role.deactivated", actor_user_id: null, entity_type: "role", entity_id: "role-area", message: "Role deactivated", created_at: "2026-09-15T08:30:00Z" }
  ];

  function addUser(user: Omit<FakeUser, "id">) {
    const created = { ...user, id: nextId("user") };
    users.set(created.mobile, created);
    return created;
  }

  addUser({
    mobile: "+919999900001",
    name: "Asha Admin",
    status: "ACTIVE",
    channels: { ADMIN: ADMIN_PERMISSIONS },
    roles: ["super_admin"]
  });

  function respond<T>(config: InternalAxiosRequestConfig, status: number, data: T): AxiosResponse<T> {
    const response: AxiosResponse<T> = {
      data,
      status,
      statusText: String(status),
      headers: new AxiosHeaders(),
      config
    };
    if (status >= 400) {
      throw new AxiosError(`Request failed with status code ${status}`, "ERR_BAD_REQUEST", config, {}, response as AxiosResponse);
    }
    return response;
  }

  const error = (config: InternalAxiosRequestConfig, status: number, code: string) =>
    respond(config, status, { detail: { code, message: code } });

  function issueTokens(userId: string, channel: Channel) {
    const access = nextId("access");
    const refresh = nextId("refresh");
    const session = { userId, channel, revoked: false };
    accessTokens.set(access, session);
    refreshTokens.set(refresh, session);
    return { access_token: access, refresh_token: refresh, token_type: "Bearer", expires_in: 900 };
  }

  function authenticate(config: InternalAxiosRequestConfig, channel: Channel) {
    const header = String(config.headers?.Authorization ?? "");
    const token = header.replace(/^Bearer /, "");
    const session = accessTokens.get(token);
    if (!session) throw respond(config, 401, { detail: "Authentication required" });
    if (session.channel !== channel) throw respond(config, 403, { detail: "Permission denied" });
    const user = [...users.values()].find((item) => item.id === session.userId);
    if (!user) throw respond(config, 401, { detail: "Authentication required" });
    return { user, permissions: user.channels[channel] ?? [] };
  }

  function requirePermission(config: InternalAxiosRequestConfig, channel: Channel, permission: string) {
    const auth = authenticate(config, channel);
    if (options.forbidAll || !auth.permissions.includes(permission)) {
      throw respond(config, 403, { detail: "Permission denied" });
    }
    return auth;
  }

  const adapter: AxiosAdapter = async (config) => {
    const method = (config.method ?? "get").toUpperCase();
    const url = new URL(config.url ?? "", "http://fake");
    const path = url.pathname;
    const body = typeof config.data === "string" && config.data ? JSON.parse(config.data) : {};
    calls.push(`${method} ${path}`);

    if (options.delayMs) {
      await new Promise((resolve) => setTimeout(resolve, options.delayMs));
    }
    if (options.failNetwork) {
      throw new AxiosError("Network Error", "ERR_NETWORK", config, {});
    }
    if (options.failPaths.some((prefix) => path.startsWith(prefix))) {
      return respond(config, 500, "Traceback (most recent call last): simulated failure");
    }

    const channelMatch = path.match(/^\/(admin|merchant|delivery)\/auth\/(.+)$/);
    if (channelMatch) {
      const channel = channelMatch[1].toUpperCase() as Channel;
      const action = channelMatch[2];
      if (action === "otp/request") {
        const user = users.get(body.mobile_number);
        const requestId = nextId("challenge");
        challenges.set(requestId, {
          mobile: user?.mobile ?? body.mobile_number,
          channel,
          attempts: 0,
          used: false,
          expired: false,
          suppressed: !user
        });
        return respond(config, 202, {
          request_id: requestId,
          message: "OTP request accepted",
          expires_in: 300,
          resend_after: 30,
          code: "OTP_REQUEST_ACCEPTED"
        });
      }
      if (action === "otp/resend") {
        const previous = challenges.get(body.request_id);
        if (!previous) return error(config, 400, "OTP_PURPOSE_MISMATCH");
        if (previous.used) return error(config, 400, "OTP_ALREADY_USED");
        previous.used = true;
        const requestId = nextId("challenge");
        challenges.set(requestId, { ...previous, attempts: 0, used: false, expired: false });
        return respond(config, 202, {
          request_id: requestId,
          message: "OTP request accepted",
          expires_in: 300,
          resend_after: 30,
          code: "OTP_REQUEST_ACCEPTED"
        });
      }
      if (action === "otp/verify") {
        const challenge = challenges.get(body.request_id);
        if (!challenge) return error(config, 400, "OTP_PURPOSE_MISMATCH");
        if (challenge.channel !== channel) return error(config, 403, "CHANNEL_NOT_ALLOWED");
        if (challenge.used) return error(config, 400, "OTP_ALREADY_USED");
        if (challenge.expired) return error(config, 400, "OTP_EXPIRED");
        if (challenge.attempts >= 5) return error(config, 400, "OTP_ATTEMPTS_EXCEEDED");
        if (challenge.suppressed || body.otp !== OTP) {
          challenge.attempts += 1;
          return error(config, 400, "OTP_INVALID");
        }
        challenge.used = true;
        const user = users.get(challenge.mobile)!;
        if (user.status === "BLOCKED") return error(config, 403, "ACCOUNT_BLOCKED");
        if (!(user.channels[channel] ?? []).length) return error(config, 403, "ROLE_NOT_ASSIGNED");
        return respond(config, 200, {
          token: issueTokens(user.id, channel),
          user_id: user.id,
          login_channel: channel,
          is_new_user: false,
          code: "OTP_VERIFIED",
          message: "OTP verified"
        });
      }
      if (action === "me") {
        const { user, permissions } = authenticate(config, channel);
        return respond(config, 200, {
          user_id: user.id,
          display_name: user.name,
          mobile_number: user.mobile,
          country_code: "+91",
          role: null,
          active_roles: user.roles,
          effective_permissions: permissions,
          login_channel: channel,
          status: user.status
        });
      }
      if (action === "token/refresh") {
        const session = refreshTokens.get(body.refresh_token);
        if (!session || session.revoked || session.channel !== channel) {
          return error(config, 401, "SESSION_REVOKED");
        }
        session.revoked = true;
        refreshTokens.delete(body.refresh_token);
        return respond(config, 200, issueTokens(session.userId, channel));
      }
      if (action === "logout") {
        const session = refreshTokens.get(body.refresh_token);
        if (session) session.revoked = true;
        return respond(config, 204, "");
      }
      if (action === "logout-all") {
        const { user } = authenticate(config, channel);
        refreshTokens.forEach((session) => {
          if (session.userId === user.id) session.revoked = true;
        });
        return respond(config, 204, "");
      }
    }

    if (path === "/admin/merchants" && method === "POST") {
      const { user } = requirePermission(config, "ADMIN", "merchants.create");
      if (merchants.some((item) => item.merchant_code === body.merchant_code)) {
        return error(config, 409, "MERCHANT_CODE_EXISTS");
      }
      if (merchants.some((item) => item.mobile_number === body.mobile_number)) {
        return error(config, 409, "MERCHANT_MOBILE_EXISTS");
      }
      const merchant = {
        id: nextId("merchant"),
        ...body,
        primary_user_id: null,
        status: "ACTIVE",
        approval_status: "APPROVED",
        role: "manager",
        allowed_channel: "MERCHANT",
        created_at: "2026-09-16T08:00:00Z",
        created_by: user.id
      };
      merchants.unshift(merchant);
      addUser({
        mobile: body.mobile_number,
        name: body.contact_person_name,
        status: "ACTIVE",
        channels: { MERCHANT: MANAGER_PERMISSIONS },
        roles: ["manager"]
      });
      return respond(config, 201, merchant);
    }
    if (path === "/admin/merchants" && method === "GET") {
      requirePermission(config, "ADMIN", "merchants.view");
      const status = url.searchParams.get("status") ?? (config.params?.status as string | undefined);
      const items = merchants.filter((item) => !status || item.status === status);
      return respond(config, 200, { items, total: items.length, limit: 20, offset: 0 });
    }
    const merchantMatch = path.match(/^\/admin\/merchants\/([^/]+)$/);
    if (merchantMatch && method === "GET") {
      requirePermission(config, "ADMIN", "merchants.view");
      const merchant = merchants.find((item) => item.id === merchantMatch[1]);
      if (!merchant) return error(config, 404, "MERCHANT_NOT_FOUND");
      return respond(config, 200, merchant);
    }

    if (path === "/merchant/delivery-users" && method === "POST") {
      const { user } = requirePermission(config, "MERCHANT", "delivery_users.create");
      if (body.delivery_user_type === "DRIVER" && (!body.driving_license_number || !body.driving_license_expiry)) {
        return respond(config, 422, {
          detail: [{ type: "value_error", loc: ["body"], msg: "Value error, Driver requires driving license number and expiry" }]
        });
      }
      if (deliveryMembers.some((item) => item.employee_code === body.employee_code && item.merchant_owner === user.id)) {
        return error(config, 409, "EMPLOYEE_CODE_EXISTS");
      }
      const member = {
        id: nextId("member"),
        merchant_id: "merchant-scope",
        user_id: nextId("user"),
        email: null,
        address: null,
        driving_license_number: null,
        driving_license_expiry: null,
        ...body,
        status: "ACTIVE",
        approval_status: "APPROVED",
        role: body.delivery_user_type === "DRIVER" ? "driver" : "helper",
        allowed_channel: "DELIVERY",
        created_at: "2026-09-16T08:00:00Z",
        merchant_owner: user.id
      };
      deliveryMembers.unshift(member);
      const { merchant_owner: _owner, ...publicMember } = member;
      void _owner;
      return respond(config, 201, publicMember);
    }
    if (path === "/merchant/delivery-users" && method === "GET") {
      const { user } = requirePermission(config, "MERCHANT", "delivery_users.view");
      const params = (config.params ?? {}) as Record<string, string>;
      const items = deliveryMembers
        .filter((item) => item.merchant_owner === user.id)
        .filter((item) => !params.delivery_user_type || item.delivery_user_type === params.delivery_user_type)
        .filter((item) => !params.status || item.status === params.status)
        .map(({ merchant_owner: _owner, ...rest }) => {
          void _owner;
          return rest;
        });
      return respond(config, 200, { items, total: items.length, limit: 20, offset: 0 });
    }
    const memberMatch = path.match(/^\/merchant\/delivery-users\/([^/]+)$/);
    if (memberMatch && method === "GET") {
      const { user } = requirePermission(config, "MERCHANT", "delivery_users.view");
      const member = deliveryMembers.find((item) => item.id === memberMatch[1] && item.merchant_owner === user.id);
      if (!member) return error(config, 404, "DELIVERY_USER_NOT_FOUND");
      const { merchant_owner: _owner, ...rest } = member;
      void _owner;
      return respond(config, 200, rest);
    }


    const userSummary = (user: FakeUser) => ({
      id: user.id,
      email: null,
      username: null,
      full_name: user.name,
      mobile_number: user.mobile,
      country_code: "+91",
      role: user.roles[0] ?? "admin_user",
      status: userStatus.get(user.id) ?? user.status,
      created_at: "2026-09-16T08:00:00Z"
    });
    const findUser = (id: string) => [...users.values()].find((item) => item.id === id);

    if (path === "/admin/users" && method === "GET") {
      requirePermission(config, "ADMIN", "users.view");
      const params = (config.params ?? {}) as Record<string, string>;
      const items = options.emptyLists
        ? []
        : [...users.values()]
            .map(userSummary)
            .filter((item) => !params.status || item.status === params.status)
            .filter((item) => !params.search || String(item.mobile_number).includes(params.search));
      return respond(config, 200, { items, total: items.length, limit: 20, offset: 0 });
    }
    const userAction = path.match(/^\/admin\/users\/([^/]+)(?:\/(.+))?$/);
    if (userAction) {
      const [, userId, action] = userAction;
      requirePermission(config, "ADMIN", "users.view");
      const user = findUser(userId);
      if (!user) return respond(config, 404, { detail: "User not found" });
      if (!action && method === "GET") return respond(config, 200, userSummary(user));
      if (method === "POST" && (action === "block" || action === "unblock" || action === "activate")) {
        requirePermission(config, "ADMIN", action === "activate" ? "users.activate" : "users.block");
        userStatus.set(user.id, action === "block" ? "BLOCKED" : "ACTIVE");
        return respond(config, 200, userSummary(user));
      }
      if (method === "POST" && action === "logout-all") {
        requirePermission(config, "ADMIN", "users.revoke_sessions");
        return respond(config, 204, "");
      }
      if (method === "GET" && action === "roles") {
        return respond(
          config,
          200,
          user.roles.map((code, index) => ({
            id: `assignment-${index}`,
            user_id: user.id,
            role_id: roles.find((role) => role.code === code)?.id ?? code,
            role_code: code,
            assigned_at: "2026-09-16T08:00:00Z",
            assigned_by: null,
            is_active: true,
            valid_from: null,
            valid_until: null,
            scope_type: "global",
            scope_id: "global"
          }))
        );
      }
      if (method === "GET" && action === "allowed-channels") {
        requirePermission(config, "ADMIN", "users.view_permissions");
        return respond(config, 200, { user_id: user.id, channels: Object.keys(user.channels) });
      }
      if (method === "GET" && action === "effective-permissions") {
        requirePermission(config, "ADMIN", "users.view_permissions");
        const channel = String((config.params as Record<string, string> | undefined)?.login_channel ?? "ADMIN") as Channel;
        return respond(config, 200, { user_id: user.id, permissions: user.channels[channel] ?? [] });
      }
    }

    if (path === "/admin/roles" && method === "GET") {
      requirePermission(config, "ADMIN", "roles.view");
      const items = options.emptyLists ? [] : roles;
      return respond(config, 200, { items, total: items.length, page: 1, page_size: 20, total_pages: items.length ? 1 : 0 });
    }
    const roleAction = path.match(/^\/admin\/roles\/([^/]+)(?:\/(.+))?$/);
    if (roleAction) {
      const [, roleId, action] = roleAction;
      requirePermission(config, "ADMIN", "roles.view");
      const role = roles.find((item) => item.id === roleId);
      if (!role) return respond(config, 404, { detail: "Role not found" });
      if (!action && method === "GET") return respond(config, 200, role);
      if (method === "POST" && (action === "activate" || action === "deactivate")) {
        requirePermission(config, "ADMIN", "roles.activate");
        if (role.code === "super_admin" && action === "deactivate") {
          return respond(config, 400, { detail: "Super Admin role is protected" });
        }
        role.is_active = action === "activate";
        return respond(config, 200, role);
      }
      if (method === "GET" && action === "users") {
        return respond(config, 200, [...users.values()].filter((user) => user.roles.includes(role.code)).map(userSummary));
      }
      if (method === "GET" && action === "permissions") return respond(config, 200, []);
      if (method === "GET" && action === "channels") return respond(config, 200, []);
    }

    if (path === "/admin/permissions/grouped") {
      requirePermission(config, "ADMIN", "permissions.view");
      const groups = options.emptyLists ? [] : permissionGroups;
      return respond(config, 200, { groups, total: groups.reduce((sum, group) => sum + group.permissions.length, 0) });
    }

    const auditDetail = path.match(/^\/admin\/audit-logs\/([^/]+)$/);
    if (auditDetail) {
      requirePermission(config, "ADMIN", "audit_logs.view");
      const log = auditLogs.find((item) => item.id === auditDetail[1]);
      if (!log) return respond(config, 404, { detail: "Audit log not found" });
      return respond(config, 200, log);
    }

    if (path === "/admin/dashboard/summary") {
      requirePermission(config, "ADMIN", "dashboard.view");
      return respond(config, 200, {
        users: users.size,
        active_users: users.size,
        blocked_users: 0,
        roles: 8,
        active_roles: 8,
        permissions: 83,
        active_permissions: 83,
        active_sessions: 1,
        audit_logs: 0
      });
    }
    if (path === "/admin/audit-logs") {
      requirePermission(config, "ADMIN", "audit_logs.view");
      const params = (config.params ?? {}) as Record<string, string>;
      const items = options.emptyLists
        ? []
        : auditLogs.filter((log) => !params.entity_type || log.entity_type === params.entity_type);
      return respond(config, 200, { items, page: 1, page_size: 25, total: items.length, total_pages: items.length ? 1 : 0 });
    }

    return respond(config, 404, { detail: "Not Found" });
  };

  return {
    adapter,
    calls,
    options,
    addUser,
    /** Simulates the access token expiring on the server. */
    expireAccessTokens() {
      accessTokens.clear();
    },
    /** Simulates every session being revoked (e.g. sign-out everywhere on another device). */
    revokeAllSessions() {
      accessTokens.clear();
      refreshTokens.forEach((session) => {
        session.revoked = true;
      });
    },
    expireChallenges() {
      challenges.forEach((challenge) => {
        challenge.expired = true;
      });
    },
    merchants,
    deliveryMembers,
    roles
  };
}

const originalAdapter = apiClient.defaults.adapter;

export function installFakeBackend(backend: FakeBackend) {
  apiClient.defaults.adapter = backend.adapter;
}

export function uninstallFakeBackend() {
  apiClient.defaults.adapter = originalAdapter;
}
