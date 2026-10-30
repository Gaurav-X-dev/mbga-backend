import type { TaskPriority, TaskStatus } from "../../api/tasks.api";
import { Badge } from "../../components/common/StatusBadge";
import { formatDate } from "../../utils/format";
import type { Tone } from "../../utils/labels";
import { TASK_PRIORITY, TASK_STATUS, isOverdue } from "./task-labels";

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  const meta = TASK_STATUS[status] ?? { label: status, tone: "neutral" as Tone };
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}

export function TaskPriorityBadge({ priority }: { priority: TaskPriority }) {
  const meta = TASK_PRIORITY[priority] ?? { label: priority, tone: "neutral" as Tone };
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}

export function DueDate({ task }: { task: { dueDate: string; dueTime?: string | null; status: TaskStatus } }) {
  const overdue = isOverdue(task);
  return (
    <span className="nowrap" style={overdue ? { color: "var(--red-600, #dc2626)", fontWeight: 600 } : undefined}>
      {formatDate(task.dueDate)}
      {task.dueTime ? ` · ${task.dueTime}` : ""}
      {overdue ? " · Overdue" : ""}
    </span>
  );
}

export function ProgressBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <span className="row nowrap" style={{ gap: 8, flexWrap: "nowrap" }} aria-label={`${pct}% complete`}>
      <span style={{ display: "block", width: 72, height: 6, borderRadius: 999, background: "var(--border)" }}>
        <span
          style={{
            display: "block",
            height: "100%",
            width: `${pct}%`,
            borderRadius: 999,
            background: pct === 100 ? "var(--green-500, #16a34a)" : "var(--blue-500, #3b82f6)"
          }}
        />
      </span>
      <small className="text-muted">{pct}%</small>
    </span>
  );
}
