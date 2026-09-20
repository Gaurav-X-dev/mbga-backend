import { apiClient } from "./client";
import { cleanParams } from "./params";

/** Admin channel: /admin/audit-logs */
export type AuditLog = {
  id: string;
  event_type: string;
  actor_user_id: string | null;
  entity_type: string | null;
  entity_id: string | null;
  message: string | null;
  created_at: string;
};

export type AuditLogListResponse = {
  items: AuditLog[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
};

export type AuditLogListParams = {
  actor_user_id?: string;
  action?: string;
  entity_type?: string;
  date_from?: string;
  date_to?: string;
  page: number;
  page_size: number;
};

export async function listAuditLogs(params: AuditLogListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<AuditLogListResponse>("/admin/audit-logs", { params: cleanParams(params), signal });
  return data;
}

export async function getAuditLog(auditLogId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<AuditLog>(`/admin/audit-logs/${encodeURIComponent(auditLogId)}`, { signal });
  return data;
}
