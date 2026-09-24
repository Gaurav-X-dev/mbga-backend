import { apiClient } from "./client";
import { cleanParams } from "./params";
import type { Permission } from "./permissions.api";
import type { User } from "./users.api";

/** Admin channel: /admin/roles */
export type Role = {
  id: string;
  name: string;
  code: string;
  description: string | null;
  is_system: boolean;
  is_active: boolean;
};

export type RoleListResponse = {
  items: Role[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
};

export type RoleListParams = {
  search?: string;
  is_active?: boolean;
  login_channel?: string;
  page: number;
  page_size: number;
};

export type RoleCreateInput = { name: string; code: string; description?: string };
export type RoleUpdateInput = { name?: string; description?: string | null };
export type RoleChannel = { login_channel: string; is_allowed: boolean };

const base = (roleId: string) => `/admin/roles/${encodeURIComponent(roleId)}`;

export async function listRoles(params: RoleListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<RoleListResponse>("/admin/roles", { params: cleanParams(params), signal });
  return data;
}

export async function getRole(roleId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<Role>(base(roleId), { signal });
  return data;
}

export async function createRole(input: RoleCreateInput) {
  const { data } = await apiClient.post<Role>("/admin/roles", input);
  return data;
}

export async function updateRole(roleId: string, input: RoleUpdateInput) {
  const { data } = await apiClient.patch<Role>(base(roleId), input);
  return data;
}

export async function deleteRole(roleId: string) {
  await apiClient.delete(base(roleId));
}

export async function setRoleActive(roleId: string, active: boolean) {
  const { data } = await apiClient.post<Role>(`${base(roleId)}/${active ? "activate" : "deactivate"}`);
  return data;
}

export async function listRolePermissions(roleId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<Permission[]>(`${base(roleId)}/permissions`, { signal });
  return data;
}

export async function replaceRolePermissions(roleId: string, permissionIds: string[]) {
  await apiClient.put(`${base(roleId)}/permissions`, { permission_ids: permissionIds });
}

export async function listRoleChannels(roleId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<RoleChannel[]>(`${base(roleId)}/channels`, { signal });
  return data;
}

export async function replaceRoleChannels(roleId: string, channels: RoleChannel[]) {
  await apiClient.put(`${base(roleId)}/channels`, { channels });
}

export async function listRoleUsers(roleId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<User[]>(`${base(roleId)}/users`, { signal });
  return data;
}
