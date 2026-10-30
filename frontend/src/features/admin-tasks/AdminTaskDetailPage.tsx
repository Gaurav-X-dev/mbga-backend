import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { normalizeError } from "../../api/errors";
import { queryKeys } from "../../api/query-keys";
import {
  getTask,
  listTaskActivity,
  listTaskMessages,
  listTeam,
  postTaskMessage,
  updateTaskStatus,
  type TaskAttachment,
  type TaskMessage,
  type TaskStatus,
  type UpdateTaskStatusInput
} from "../../api/tasks.api";
import { Button, ButtonLink } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { UserAvatar } from "../../components/common/StatusBadge";
import { Alert, EmptyState, ErrorState, InlineError, LoadingSkeleton } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, Select, Textarea } from "../../components/forms/Field";
import { Card, DetailsPanel, PageHeader } from "../../components/layout/Page";
import { formatDateTime, formatRelativeTime, humanize } from "../../utils/format";
import { roleLabel } from "../../utils/labels";
import { TASK_CATEGORIES, TASK_STATUS, statusOptions } from "./task-labels";
import { DueDate, ProgressBar, TaskPriorityBadge, TaskStatusBadge } from "./task-meta";
import { useAuth } from "../../auth/auth-context";

export function AdminTaskDetailPage() {
  const auth = useAuth();
  const { taskId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const merchantId = searchParams.get("merchant") ?? (auth.channel === "merchant" ? (auth.user?.merchant as any)?.id || "merch-current" : "");
  const backHref = auth.channel === "merchant" ? "/merchant/tasks" : merchantId ? `/admin/tasks?merchant=${encodeURIComponent(merchantId)}` : "/admin/tasks";

  const task = useQuery({
    queryKey: queryKeys.tasks.detail(merchantId, taskId),
    queryFn: ({ signal }) => getTask(merchantId, taskId, signal),
    enabled: Boolean(merchantId && taskId)
  });
  const team = useQuery({
    queryKey: queryKeys.tasks.team(merchantId),
    queryFn: ({ signal }) => listTeam(merchantId, signal),
    enabled: Boolean(merchantId),
    staleTime: 5 * 60_000
  });
  const teamById = useMemo(() => new Map((team.data ?? []).map((member) => [member.id, member])), [team.data]);

  if (!merchantId) {
    return (
      <div className="page">
        <Card>
          <EmptyState
            icon="store"
            title="Merchant not specified"
            description="Open the task from the Tasks list so the panel knows which merchant it belongs to."
            action={<ButtonLink to={auth.channel === "merchant" ? "/merchant/tasks" : "/admin/tasks"} variant="secondary">Back to tasks</ButtonLink>}
          />
        </Card>
      </div>
    );
  }

  if (task.isLoading) return <LoadingSkeleton rows={8} label="Loading task" />;
  if (task.error || !task.data) {
    return (
      <div className="page">
        <Card>
          <ErrorState error={task.error} onRetry={() => void task.refetch()} />
        </Card>
      </div>
    );
  }

  const data = task.data;
  return (
    <div className="page admin-task-detail-page">
      <PageHeader
        eyebrow={<span className="mono">{data.id}</span>}
        title={data.title}
        documentTitle={`${data.id} · Tasks`}
        meta={
          <span className="row" style={{ gap: 8 }}>
            <TaskStatusBadge status={data.status} />
            <TaskPriorityBadge priority={data.priority} />
            <span className="text-muted text-small">
              Created by {data.createdByName} · {formatRelativeTime(data.createdAt)}
            </span>
          </span>
        }
        actions={
          <ButtonLink to={backHref} variant="secondary" icon="arrowLeft">
            All tasks
          </ButtonLink>
        }
      />

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 2fr) minmax(300px, 1fr)", gap: "var(--space-5)", alignItems: "start" }}>
        <div className="stack-lg">
          <Card title="Description">
            {data.description ? <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{data.description}</p> : <p className="text-muted">No description.</p>}
            {data.attachments?.length ? <Attachments items={data.attachments} /> : null}
          </Card>
          <Thread merchantId={merchantId} taskId={taskId} teamById={teamById} team={team.data ?? []} />
        </div>

        <div className="stack-lg">
          <StatusPanel merchantId={merchantId} taskId={taskId} status={data.status} progress={data.progress} />
          <Card title="Details">
            <DetailsPanel
              columns={1}
              items={[
                { label: "Due", value: <DueDate task={data} /> },
                { label: "Progress", value: <ProgressBar value={data.progress} /> },
                {
                  label: "Assigned to",
                  value: (data.assignedUserIds ?? []).length ? (
                    <ul className="list-plain stack" style={{ gap: 6 }}>
                      {(data.assignedUserIds ?? []).map((id) => {
                        const member = teamById.get(id);
                        return (
                          <li key={id} className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
                            <UserAvatar name={member?.name ?? "?"} />
                            <span className="cell-stack">
                              <span>{member?.name ?? "Former member"}</span>
                              {member ? <small>{roleLabel(member.role)}</small> : null}
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  ) : (
                    "Unassigned"
                  )
                },
                { label: "Category", value: data.category ? (TASK_CATEGORIES.find((c) => c.value === data.category)?.label ?? data.category) : "—" },
                {
                  label: "Related to",
                  value: data.relatedType ? `${humanize(data.relatedType)} · ${data.relatedLabel ?? data.relatedId ?? ""}` : "—",
                  hidden: !data.relatedType
                },
                { label: "Last updated", value: formatDateTime(data.updatedAt) }
              ]}
            />
          </Card>
          <Activity merchantId={merchantId} taskId={taskId} />
        </div>
      </div>
    </div>
  );
}

function StatusPanel({ merchantId, taskId, status, progress }: { merchantId: string; taskId: string; status: TaskStatus; progress: number }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ status, progress: String(progress), note: "" });
  useEffect(() => setForm({ status, progress: String(progress), note: "" }), [status, progress]);

  const progressValue = Number.parseInt(form.progress, 10);
  const progressError = Number.isNaN(progressValue) || progressValue < 0 || progressValue > 100 ? "Use a number from 0 to 100." : undefined;

  const mutation = useMutation({
    mutationFn: (input: UpdateTaskStatusInput) => updateTaskStatus(merchantId, taskId, input),
    onSuccess: () => {
      toast.success("Task updated.");
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
    }
  });

  // Only what changed is sent, so no duplicate thread entries are written.
  const input: UpdateTaskStatusInput = {
    ...(form.status !== status ? { status: form.status } : {}),
    ...(!progressError && progressValue !== progress && form.status !== "COMPLETED" ? { progress: progressValue } : {}),
    ...(form.note.trim() ? { note: form.note.trim() } : {})
  };
  const dirty = Object.keys(input).length > 0;

  return (
    <Card title="Update" subtitle="Each change is posted to the thread.">
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          if (dirty && !progressError) mutation.mutate(input);
        }}
      >
        <div className="grid-2">
          <Field label="Status">
            <Select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value as TaskStatus })} options={statusOptions} />
          </Field>
          <Field label="Progress %" error={progressError}>
            <Input
              type="number"
              min={0}
              max={100}
              step={5}
              value={form.status === "COMPLETED" ? "100" : form.progress}
              disabled={form.status === "COMPLETED"}
              onChange={(event) => setForm({ ...form, progress: event.target.value })}
            />
          </Field>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          step={5}
          aria-label="Progress"
          value={form.status === "COMPLETED" ? 100 : progressError ? progress : progressValue}
          disabled={form.status === "COMPLETED"}
          onChange={(event) => setForm({ ...form, progress: event.target.value })}
        />
        <Field label="Note" optional>
          <Textarea value={form.note} onChange={(event) => setForm({ ...form, note: event.target.value })} rows={2} maxLength={5000} />
        </Field>
        {form.status === "COMPLETED" && status !== "COMPLETED" ? <p className="meta">Completing the task sets progress to 100%.</p> : null}
        {mutation.error ? <Alert tone="error">{normalizeError(mutation.error).userMessage}</Alert> : null}
        <Button type="submit" icon="check" disabled={!dirty || Boolean(progressError)} loading={mutation.isPending} loadingText="Saving…">
          Save update
        </Button>
      </form>
    </Card>
  );
}

function Thread({
  merchantId,
  taskId,
  team,
  teamById
}: {
  merchantId: string;
  taskId: string;
  team: Array<{ id: string; name: string }>;
  teamById: Map<string, { name: string }>;
}) {
  const queryClient = useQueryClient();
  const messages = useQuery({
    queryKey: queryKeys.tasks.messages(merchantId, taskId),
    queryFn: ({ signal }) => listTaskMessages(merchantId, taskId, signal),
    refetchInterval: 30_000
  });
  const [text, setText] = useState("");
  const [mentions, setMentions] = useState<string[]>([]);

  const send = useMutation({
    mutationFn: () => postTaskMessage(merchantId, taskId, text.trim(), mentions),
    onSuccess: () => {
      setText("");
      setMentions([]);
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(merchantId, taskId) });
    }
  });

  return (
    <Card title="Updates" subtitle={messages.data ? `${messages.data.length} in this thread` : undefined}>
      <div className="stack">
        {messages.isLoading ? (
          <LoadingSkeleton rows={4} label="Loading updates" />
        ) : messages.error ? (
          <InlineError error={messages.error} onRetry={() => void messages.refetch()} />
        ) : !messages.data?.length ? (
          <EmptyState icon="inbox" title="No updates yet" description="Post the first update below." />
        ) : (
          <ol className="list-plain stack" style={{ gap: "var(--space-4)" }}>
            {messages.data.map((message) => (
              <MessageItem key={message.id} message={message} />
            ))}
          </ol>
        )}

        <form
          className="stack"
          style={{ borderTop: "1px solid var(--border)", paddingTop: "var(--space-4)" }}
          onSubmit={(event) => {
            event.preventDefault();
            if (text.trim()) send.mutate();
          }}
        >
          <Field label="Post an update" hideLabel>
            <Textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={3}
              maxLength={5000}
              placeholder="Write an update…  (Ctrl+Enter to send)"
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && text.trim()) send.mutate();
              }}
            />
          </Field>
          <div className="row-between" style={{ gap: "var(--space-3)", flexWrap: "wrap" }}>
            <span className="row" style={{ gap: 6 }}>
              <Select
                className="select--sm"
                aria-label="Mention someone"
                value=""
                placeholder="@ Mention…"
                onChange={(event) => event.target.value && setMentions((previous) => [...new Set([...previous, event.target.value])])}
                options={team.filter((member) => !mentions.includes(member.id)).map((member) => ({ value: member.id, label: member.name }))}
              />
              {mentions.map((id) => (
                <button
                  key={id}
                  type="button"
                  className="badge badge--info"
                  onClick={() => setMentions((previous) => previous.filter((item) => item !== id))}
                  title="Remove mention"
                >
                  @{teamById.get(id)?.name ?? id} ✕
                </button>
              ))}
            </span>
            <Button type="submit" icon="send" disabled={!text.trim()} loading={send.isPending} loadingText="Posting…">
              Post update
            </Button>
          </div>
          {send.error ? <Alert tone="error">{normalizeError(send.error).userMessage}</Alert> : null}
        </form>
      </div>
    </Card>
  );
}

function MessageItem({ message }: { message: TaskMessage }) {
  const system = message.statusChange || message.progressChange || message.kind === "STATUS_CHANGE";
  return (
    <li className="row" style={{ gap: "var(--space-3)", alignItems: "flex-start", flexWrap: "nowrap" }}>
      {system ? (
        <span className="mini-stat__icon tone-slate" aria-hidden="true">
          <Icon name="activity" size={14} />
        </span>
      ) : (
        <UserAvatar name={message.authorName} />
      )}
      <div className="stack" style={{ gap: 4, minWidth: 0, flex: 1 }}>
        <div className="row" style={{ gap: 8 }}>
          <strong>{message.authorName}</strong>
          <time className="text-muted text-small" dateTime={message.createdAt} title={formatDateTime(message.createdAt)}>
            {formatRelativeTime(message.createdAt)}
          </time>
        </div>
        {message.statusChange ? (
          <span className="text-small">
            Moved status from <strong>{TASK_STATUS[message.statusChange.from]?.label}</strong> to{" "}
            <strong>{TASK_STATUS[message.statusChange.to]?.label}</strong>
          </span>
        ) : null}
        {message.progressChange ? (
          <span className="text-small">
            Progress {message.progressChange.from}% → <strong>{message.progressChange.to}%</strong>
          </span>
        ) : null}
        {message.text ? <p style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{message.text}</p> : null}
        {message.mentions?.length ? (
          <span className="text-small text-muted">Mentioned {message.mentions.map((mention) => `@${mention.name}`).join(", ")}</span>
        ) : null}
        {message.attachments?.length ? <Attachments items={message.attachments} /> : null}
      </div>
    </li>
  );
}

function Attachments({ items }: { items: TaskAttachment[] }) {
  return (
    <ul className="list-plain row" style={{ gap: 8, marginTop: 8 }}>
      {items.map((item) =>
        item.kind === "IMAGE" && item.uri ? (
          <li key={item.id}>
            <a href={item.uri} target="_blank" rel="noreferrer" title={item.name}>
              <img src={item.uri} alt={item.name} style={{ width: 96, height: 72, objectFit: "cover", borderRadius: 8, border: "1px solid var(--border)" }} />
            </a>
          </li>
        ) : (
          <li key={item.id} className="badge badge--neutral" title={`${item.name} · ${Math.ceil(item.size / 1024)} KB`}>
            <Icon name="fileText" size={12} /> {item.name}
          </li>
        )
      )}
    </ul>
  );
}

function Activity({ merchantId, taskId }: { merchantId: string; taskId: string }) {
  const query = useQuery({
    queryKey: queryKeys.tasks.activity(merchantId, taskId),
    queryFn: ({ signal }) => listTaskActivity(merchantId, taskId, signal)
  });
  return (
    <Card title="Activity">
      {query.isLoading ? (
        <LoadingSkeleton rows={3} label="Loading activity" />
      ) : query.error ? (
        <InlineError error={query.error} onRetry={() => void query.refetch()} />
      ) : !query.data?.length ? (
        <p className="text-muted">No activity yet.</p>
      ) : (
        <ul className="timeline">
          {[...query.data].reverse().map((entry) => (
            <li key={entry.id}>
              <span>
                <strong>{entry.actorName}</strong> {entry.action}
              </span>
              <div className="text-muted text-small" title={formatDateTime(entry.at)}>
                {formatRelativeTime(entry.at)}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export default AdminTaskDetailPage;
