import { apiClient } from "./client";

/** Admin channel: /admin/permissions (read-only catalogue, seeded by the backend) */
export type Permission = {
  id: string;
  name: string;
  code: string;
  module: string;
  action: string;
  description: string | null;
  is_system: boolean;
  is_active: boolean;
};

export type PermissionGroup = { module: string; permissions: Permission[] };
export type PermissionGroupedResponse = { groups: PermissionGroup[]; total: number };

export async function listPermissionsGrouped(signal?: AbortSignal) {
  const { data } = await apiClient.get<PermissionGroupedResponse>("/admin/permissions/grouped", {
    params: { is_active: true },
    signal
  });
  return data;
}
