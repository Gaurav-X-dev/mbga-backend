import type { TaskCategory, TaskPriority, TaskStatus } from "../../api/tasks.api";
import type { Tone } from "../../utils/labels";

export const TASK_STATUS: Record<TaskStatus, { label: string; tone: Tone }> = {
  NOT_STARTED: { label: "Not started", tone: "neutral" },
  IN_PROGRESS: { label: "In progress", tone: "info" },
  PENDING: { label: "Pending", tone: "warning" },
  ON_HOLD: { label: "On hold", tone: "accent" },
  COMPLETED: { label: "Completed", tone: "success" }
};

export const TASK_PRIORITY: Record<TaskPriority, { label: string; tone: Tone }> = {
  LOW: { label: "Low", tone: "neutral" },
  MEDIUM: { label: "Medium", tone: "info" },
  HIGH: { label: "High", tone: "warning" },
  CRITICAL: { label: "Critical", tone: "danger" }
};

export const TASK_CATEGORIES: Array<{ value: TaskCategory; label: string }> = [
  { value: "GENERAL", label: "General" },
  { value: "STOCK", label: "Stock" },
  { value: "DELIVERY", label: "Delivery" },
  { value: "CUSTOMER", label: "Customer" },
  { value: "MAINTENANCE", label: "Maintenance" },
  { value: "ADMIN", label: "Admin" }
];

export const statusOptions = Object.entries(TASK_STATUS).map(([value, meta]) => ({ value, label: meta.label }));
export const priorityOptions = Object.entries(TASK_PRIORITY).map(([value, meta]) => ({ value, label: meta.label }));

export function isOverdue(task: { dueDate: string; status: TaskStatus }) {
  return task.status !== "COMPLETED" && task.dueDate < new Date().toISOString().slice(0, 10);
}
