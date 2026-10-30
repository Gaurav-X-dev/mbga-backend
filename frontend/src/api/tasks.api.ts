import { apiClient } from "./client";
import { cleanParams } from "./params";

/** Admin channel: /admin/tasks and /admin/team. Merchant-scoped - `merchantId` on every call. */
export type TaskStatus = "NOT_STARTED" | "IN_PROGRESS" | "PENDING" | "ON_HOLD" | "COMPLETED";
export type TaskPriority = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type TaskCategory = "GENERAL" | "STOCK" | "DELIVERY" | "CUSTOMER" | "MAINTENANCE" | "ADMIN";
export type TaskRelatedType = "CUSTOMER" | "ORDER" | "DELIVERY" | "INVENTORY";
export type TaskScope = "ALL" | "MY" | "ASSIGNED" | "COMPLETED";
export type TaskDue = "TODAY" | "TOMORROW" | "THIS_WEEK" | "OVERDUE";

export type TeamMember = { id: string; name: string; role: string; branchName?: string | null };

export type TaskAttachment = {
  id: string;
  kind: "IMAGE" | "FILE";
  /** Set for images only; files are opened through a short-lived document URL. */
  uri?: string | null;
  name: string;
  mimeType: string;
  size: number;
  uploadedBy: string;
  uploadedByName: string;
  uploadedAt: string;
  fileId: string;
};

export type Task = {
  id: string;
  title: string;
  description: string;
  status: TaskStatus;
  priority: TaskPriority;
  progress: number;
  category?: TaskCategory | null;
  assignedUserIds?: string[];
  createdByUserId: string;
  createdByName: string;
  dueDate: string;
  dueTime?: string | null;
  relatedType?: TaskRelatedType | null;
  relatedId?: string | null;
  relatedLabel?: string | null;
  attachments?: TaskAttachment[];
  messageCount: number;
  createdAt: string;
  updatedAt: string;
};

export type TaskPage = { items: Task[]; page: number; pageSize: number; total: number };

export type TaskMessage = {
  id: string;
  taskId: string;
  /** e.g. COMMENT or STATUS_CHANGE (server-written). */
  kind: string;
  authorId: string;
  authorName: string;
  text: string;
  mentions?: Array<{ userId: string; name: string }>;
  attachments?: TaskAttachment[];
  statusChange?: { from: TaskStatus; to: TaskStatus } | null;
  progressChange?: { from: number; to: number } | null;
  createdAt: string;
};

export type TaskActivity = { id: string; taskId: string; at: string; actorName: string; action: string };

export type TaskListParams = {
  merchantId: string;
  scope?: TaskScope;
  status?: TaskStatus[];
  priority?: TaskPriority[];
  due?: TaskDue;
  search?: string;
  page: number;
  pageSize: number;
};

export type CreateTaskInput = {
  title: string;
  description?: string;
  assignedUserIds: string[];
  priority: TaskPriority;
  dueDate: string;
  dueTime?: string;
  category?: TaskCategory;
  relatedType?: TaskRelatedType;
  relatedId?: string;
  relatedLabel?: string;
};

export type UpdateTaskStatusInput = { status?: TaskStatus; progress?: number; note?: string };

const scoped = (merchantId: string) => ({ params: { merchantId } });
const task = (taskId: string) => `/admin/tasks/${encodeURIComponent(taskId)}`;

export async function listTeam(merchantId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<TeamMember[]>("/admin/team", { ...scoped(merchantId), signal });
  return data;
}

export async function listTasks(params: TaskListParams, signal?: AbortSignal) {
  const { data } = await apiClient.get<TaskPage>("/admin/tasks", {
    params: cleanParams({ ...params, status: params.status?.length ? params.status : undefined, priority: params.priority?.length ? params.priority : undefined }),
    // status and priority repeat (`status=A&status=B`), not `status[]=A`.
    paramsSerializer: { indexes: null },
    signal
  });
  return data;
}

export async function getTask(merchantId: string, taskId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<Task>(task(taskId), { ...scoped(merchantId), signal });
  return data;
}

export async function createTask(merchantId: string, input: CreateTaskInput) {
  const { data } = await apiClient.post<Task>("/admin/tasks", { ...input, attachments: [] }, scoped(merchantId));
  return data;
}

export async function updateTaskStatus(merchantId: string, taskId: string, input: UpdateTaskStatusInput) {
  const { data } = await apiClient.patch<Task>(`${task(taskId)}/status`, input, scoped(merchantId));
  return data;
}

export async function listTaskMessages(merchantId: string, taskId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<TaskMessage[]>(`${task(taskId)}/messages`, { ...scoped(merchantId), signal });
  return data;
}

export async function postTaskMessage(merchantId: string, taskId: string, text: string, mentionUserIds: string[]) {
  const { data } = await apiClient.post<TaskMessage>(
    `${task(taskId)}/messages`,
    { text, mentions: mentionUserIds.map((userId) => ({ userId })), attachments: [] },
    scoped(merchantId)
  );
  return data;
}

export async function listTaskActivity(merchantId: string, taskId: string, signal?: AbortSignal) {
  const { data } = await apiClient.get<TaskActivity[]>(`${task(taskId)}/activity`, { ...scoped(merchantId), signal });
  return data;
}
