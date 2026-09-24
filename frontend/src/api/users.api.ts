import { apiClient } from "./client";
import { cleanParams } from "./params";

/** Admin channel: /admin/users */
export type User = {
  id: string;
  email: string | null;
  username: string | null;
  full_name: string | null;
  mobile_number: string | null;
  country_code: string | null;
  role: string;
  status: string;
  created_at: string | null;
};

export type UserListResponse = {
  items: User[];
  total: number;
  limit: number;
  offset: number;
};

export type UserListParams = {
  search?: string;
  status?: string;
  limit: number;
  offset: number;
};

export type UserCreateInput = {
  full_name?: string;
  mobile_number?: string;
  email?: string;
  country_code?: string;
  status?: string;
};

export type UserUpdateInput = {
  full_name?: string | null;
  email?: string | null;
};

export type UserRoleAssignment = {
  id: string;
  user_id: string;
  role_id: string;
  role_code: string | null;
  assigned_at: string;
  assigned_by: string | null;
  is_active: boolean;
  valid_from: string | null;
  valid_until: string | null;
  scope_type: string;
  scope_id: string;
};

export type EffectivePermissions = { user_id: string; permissions: string[] };
export type AllowedChannels = { user_id: string; channels: string[] };

const base = (userId: string) => `/admin/users/${encodeURIComponent(userId)}`;

export async function listUsers(params: UserListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<UserListResponse>("/admin/users", { params: cleanParams(params), signal });
  return data;
}

export async function getUser(userId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<User>(base(userId), { signal });
  return data;
}

export async function createUser(input: UserCreateInput) {
  const { data } = await apiClient.post<User>("/admin/users", input);
  return data;
}

export async function updateUser(userId: string, input: UserUpdateInput) {
  const { data } = await apiClient.patch<User>(base(userId), input);
  return data;
}

export type UserStatusAction = "activate" | "block" | "unblock";

export async function changeUserStatus(userId: string, action: UserStatusAction) {
  const { data } = await apiClient.post<User>(`${base(userId)}/${action}`);
  return data;
}

export async function signOutUserEverywhere(userId: string) {
  await apiClient.post(`${base(userId)}/logout-all`);
}

export async function getUserEffectivePermissions(userId: string, loginChannel: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<EffectivePermissions>(`${base(userId)}/effective-permissions`, {
    params: { login_channel: loginChannel },
    signal
  });
  return data;
}

export async function getUserAllowedChannels(userId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<AllowedChannels>(`${base(userId)}/allowed-channels`, { signal });
  return data;
}

export async function listUserRoles(userId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<UserRoleAssignment[]>(`${base(userId)}/roles`, { signal });
  return data;
}

export async function assignUserRole(userId: string, roleId: string) {
  const { data } = await apiClient.post<UserRoleAssignment>(`${base(userId)}/roles`, { role_id: roleId });
  return data;
}

export async function removeUserRole(userId: string, assignmentId: string) {
  await apiClient.delete(`${base(userId)}/roles/${encodeURIComponent(assignmentId)}`);
}
