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
  /**
   * The permissions this one cannot be used without, by code. The backend grants these
   * alongside it on save, so the matrix ticks them here too rather than letting the screen
   * disagree with what was stored.
   */
  requires: string[];
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
