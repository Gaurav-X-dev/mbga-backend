import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { normalizeError } from "../../api/errors";
import { listMerchants } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import {
  createTask,
  listTasks,
  listTeam,
  type CreateTaskInput,
  type Task,
  type TaskCategory,
  type TaskDue,
  type TaskPriority,
  type TaskScope,
  type TaskStatus,
  type TeamMember
} from "../../api/tasks.api";
import { useOptionalAuth } from "../../auth/auth-context";
import { Button } from "../../components/common/Button";
import { UserAvatar } from "../../components/common/StatusBadge";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, InlineError, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Checkbox, Field, Input, SearchInput, Select, Textarea } from "../../components/forms/Field";
import { Card, PageHeader } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatRelativeTime, todayInputValue } from "../../utils/format";
import { roleLabel } from "../../utils/labels";
import { TASK_CATEGORIES, priorityOptions, statusOptions } from "./task-labels";
import { DueDate, ProgressBar, TaskPriorityBadge, TaskStatusBadge } from "./task-meta";

const PAGE_SIZE = 20;
const FILTERS = ["merchant", "scope", "status", "priority", "due", "search"] as const;

const SCOPES: Array<{ value: TaskScope; label: string }> = [
  { value: "ALL", label: "All tasks" },
  { value: "MY", label: "Assigned to me" },
  { value: "ASSIGNED", label: "Created by me" },
  { value: "COMPLETED", label: "Completed" }
];

const DUE_OPTIONS: Array<{ value: TaskDue; label: string }> = [
  { value: "OVERDUE", label: "Overdue" },
  { value: "TODAY", label: "Due today" },
  { value: "TOMORROW", label: "Due tomorrow" },
  { value: "THIS_WEEK", label: "Due this week" }
];

export interface AdminTasksPageProps {
  merchantId?: string;
  isMerchantPanel?: boolean;
  title?: string;
}

export function AdminTasksPage({ merchantId: propMerchantId, isMerchantPanel = false, title = "Tasks" }: AdminTasksPageProps = {}) {
  const auth = useOptionalAuth();
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { values, page, setFilter, setPage, clearFilters } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));
  const merchantId =
    propMerchantId ||
    (isMerchantPanel ? (auth?.user?.merchant as any)?.id || "merch-current" : undefined) ||
    values.merchant;
  const scope = (values.scope || "ALL") as TaskScope;
  const [creating, setCreating] = useState(false);

  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: queryKeys.merchants.list(merchantParams),
    queryFn: ({ signal }) => listMerchants(merchantParams, signal),
    enabled: !isMerchantPanel,
    staleTime: 5 * 60_000
  });

  // Tasks belong to a merchant's team, so open on the first merchant rather than an empty screen.
  useEffect(() => {
    if (isMerchantPanel) return;
    const first = merchants.data?.items[0];
    if (!values.merchant && first) setFilter("merchant", first.id);
  }, [isMerchantPanel, values.merchant, merchants.data, setFilter]);

  const team = useQuery({
    queryKey: queryKeys.tasks.team(merchantId),
    queryFn: ({ signal }) => listTeam(merchantId, signal),
    enabled: Boolean(merchantId),
    staleTime: 5 * 60_000
  });
  const teamById = useMemo(() => new Map((team.data ?? []).map((member) => [member.id, member])), [team.data]);

  const params = {
    merchantId,
    scope,
    status: values.status ? [values.status as TaskStatus] : undefined,
    priority: values.priority ? [values.priority as TaskPriority] : undefined,
    due: (values.due || undefined) as TaskDue | undefined,
    search: values.search || undefined,
    page,
    pageSize: PAGE_SIZE
  };
  const query = useQuery({
    queryKey: queryKeys.tasks.list(params),
    queryFn: ({ signal }) => listTasks(params, signal),
    enabled: Boolean(merchantId),
    placeholderData: keepPreviousData
  });

  const detailHref = (task: Task) =>
    isMerchantPanel
      ? `/merchant/tasks/${encodeURIComponent(task.id)}`
      : `/admin/tasks/${encodeURIComponent(task.id)}?merchant=${encodeURIComponent(merchantId)}`;
  const filtered = Boolean(values.status || values.priority || values.due || values.search);

  const columns: Column<Task>[] = [
    {
      key: "task",
      header: "Task",
      primary: true,
      render: (task) => (
        <div className="cell-stack">
          <Link
            to={detailHref(task)}
            className="cell-primary__title"
            style={{ display: "block", maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            title={task.title}
          >
            {task.title}
          </Link>
          <small className="nowrap">
            <span className="mono">{task.id}</span>
            {task.category ? ` · ${TASK_CATEGORIES.find((c) => c.value === task.category)?.label ?? task.category}` : ""}
            {task.messageCount ? ` · ${task.messageCount} updates` : ""}
          </small>
        </div>
      )
    },
    {
      key: "assignees",
      header: "Assigned to",
      render: (task) => <Assignees ids={task.assignedUserIds ?? []} teamById={teamById} />
    },
    { key: "priority", header: "Priority", sortValue: (task) => ["LOW", "MEDIUM", "HIGH", "CRITICAL"].indexOf(task.priority), render: (task) => <TaskPriorityBadge priority={task.priority} /> },
    { key: "due", header: "Due", sortValue: (task) => task.dueDate, render: (task) => <DueDate task={task} /> },
    { key: "progress", header: "Progress", sortValue: (task) => task.progress, hideOnMobile: true, render: (task) => <ProgressBar value={task.progress} /> },
    { key: "status", header: "Status", sortValue: (task) => task.status, render: (task) => <TaskStatusBadge status={task.status} /> },
    {
      key: "updated",
      header: "Last activity",
      hideOnMobile: true,
      sortValue: (task) => task.updatedAt,
      render: (task) => <small className="nowrap text-muted">{formatRelativeTime(task.updatedAt)}</small>
    }
  ];

  return (
    <div className="page admin-tasks-page">
      <PageHeader
        title={title}
        documentTitle={title}
        description={isMerchantPanel ? "Assign work to your team and follow it through to done." : "Assign work to a merchant's team and follow it through to done."}
        meta={<RefreshIndicator active={query.isFetching && !query.isLoading} />}
        actions={
          <>
            {!isMerchantPanel ? (
              <Field label="Merchant" hideLabel>
                <Select
                  value={merchantId}
                  onChange={(event) => setFilter("merchant", event.target.value)}
                  placeholder={merchants.isLoading ? "Loading merchants…" : "Select a merchant"}
                  disabled={merchants.isLoading}
                  options={(merchants.data?.items ?? []).map((merchant) => ({ value: merchant.id, label: merchant.business_name }))}
                />
              </Field>
            ) : null}
            <Button icon="plus" onClick={() => setCreating(true)} disabled={!merchantId}>
              New task
            </Button>
          </>
        }
      />

      {merchants.error ? <InlineError error={merchants.error} title="Merchants could not be loaded" onRetry={() => void merchants.refetch()} /> : null}

      {!merchantId ? (
        merchants.isLoading ? (
          <LoadingSkeleton rows={4} label="Loading merchants" />
        ) : (
          <Card>
            <EmptyState icon="store" title="Choose a merchant" description="Tasks belong to a merchant's team. Pick one above." />
          </Card>
        )
      ) : (
        <Card bodyless className="table-card">
          <div className="status-tabs status-tabs--card" role="tablist" aria-label="Task scope">
            {SCOPES.map((item) => (
              <button key={item.value} type="button" role="tab" aria-selected={scope === item.value} onClick={() => setFilter("scope", item.value === "ALL" ? "" : item.value)}>
                {item.label}
              </button>
            ))}
          </div>

          <TableHeader title={SCOPES.find((item) => item.value === scope)?.label ?? "Tasks"} count={query.data?.total} description="Most recent activity first." />

          <FilterBar
            onReset={() => clearFilters(["status", "priority", "due", "search"])}
            canReset={filtered}
          >
            <SearchInput label="Search tasks" placeholder="Search title, task ID or person" value={searchText} onChange={(event) => setSearchText(event.target.value)} />
            <Field label="Status" hideLabel>
              <Select value={values.status} onChange={(event) => setFilter("status", event.target.value)} placeholder="Any status" options={statusOptions} />
            </Field>
            <Field label="Priority" hideLabel>
              <Select value={values.priority} onChange={(event) => setFilter("priority", event.target.value)} placeholder="Any priority" options={priorityOptions} />
            </Field>
            <Field label="Due" hideLabel>
              <Select value={values.due} onChange={(event) => setFilter("due", event.target.value)} placeholder="Any due date" options={DUE_OPTIONS} />
            </Field>
          </FilterBar>

          {query.error && query.data ? (
            <div style={{ padding: "var(--space-4)" }}>
              <InlineError error={query.error} title="The list could not be refreshed" onRetry={() => void query.refetch()} />
            </div>
          ) : null}

          <DataTable
            caption="Tasks"
            columns={columns}
            rows={query.data?.items}
            getRowKey={(task) => task.id}
            getRowHref={detailHref}
            rowLabel={(task) => task.title}
            rowActions={(task) => [{ label: "Open task", icon: "eye", onSelect: () => navigate(detailHref(task)) }]}
            isLoading={query.isLoading}
            error={query.data ? undefined : query.error}
            onRetry={() => void query.refetch()}
            empty={
              filtered ? (
                <EmptyState icon="search" title="No tasks match your filters" description="Try a different status, priority or search." />
              ) : (
                <EmptyState
                  icon="checkCircle"
                  title="No tasks here"
                  description="Create a task to assign work to the team."
                  action={<Button icon="plus" onClick={() => setCreating(true)}>New task</Button>}
                />
              )
            }
            footer={<Pagination page={page} pageSize={PAGE_SIZE} total={query.data?.total ?? 0} onPageChange={setPage} itemLabel="tasks" disabled={query.isFetching} />}
          />
        </Card>
      )}

      <CreateTaskDialog
        open={creating}
        team={team.data ?? []}
        teamLoading={team.isLoading}
        onClose={() => setCreating(false)}
        onSubmit={async (input) => {
          const created = await createTask(merchantId, input);
          toast.success(`Task ${created.id} created.`);
          void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
          navigate(detailHref(created));
        }}
      />
    </div>
  );
}

function Assignees({ ids, teamById }: { ids: string[]; teamById: Map<string, TeamMember> }) {
  if (!ids.length) return <span className="text-muted">Unassigned</span>;
  const names = ids.map((id) => teamById.get(id)?.name ?? "Former member");
  return (
    <span className="row nowrap" style={{ gap: 6, flexWrap: "nowrap" }} title={names.join(", ")}>
      <UserAvatar name={names[0]} />
      <span>
        {names[0]}
        {names.length > 1 ? <small className="text-muted"> +{names.length - 1}</small> : null}
      </span>
    </span>
  );
}

function CreateTaskDialog({
  open,
  team,
  teamLoading,
  onClose,
  onSubmit
}: {
  open: boolean;
  team: TeamMember[];
  teamLoading: boolean;
  onClose: () => void;
  onSubmit: (input: CreateTaskInput) => Promise<void>;
}) {
  const empty = {
    title: "",
    description: "",
    priority: "MEDIUM" as TaskPriority,
    dueDate: todayInputValue(),
    dueTime: "",
    category: "GENERAL" as TaskCategory,
    assignees: [] as string[]
  };
  const [form, setForm] = useState(empty);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (open) {
      setForm({ ...empty, dueDate: todayInputValue() });
      setSubmitted(false);
    }
    // empty is rebuilt each render; resetting only on open is intended.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const mutation = useMutation({
    mutationFn: onSubmit,
    onSuccess: onClose
  });

  const errors = {
    title: form.title.trim() ? undefined : "Give the task a title.",
    assignees: form.assignees.length ? undefined : "Assign at least one person.",
    dueDate: form.dueDate ? undefined : "Choose a due date."
  };
  const valid = !Object.values(errors).some(Boolean);

  function submit() {
    setSubmitted(true);
    if (!valid) return;
    mutation.mutate({
      title: form.title.trim(),
      description: form.description.trim(),
      priority: form.priority,
      dueDate: form.dueDate,
      dueTime: form.dueTime || undefined,
      category: form.category,
      assignedUserIds: form.assignees
    });
  }

  function toggle(id: string) {
    setForm((previous) => ({
      ...previous,
      assignees: previous.assignees.includes(id) ? previous.assignees.filter((item) => item !== id) : [...previous.assignees, id]
    }));
  }

  return (
    <Modal
      open={open}
      wide
      title="New task"
      description="Everyone assigned is notified."
      onClose={() => {
        mutation.reset();
        onClose();
      }}
      busy={mutation.isPending}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={mutation.isPending}>
            Cancel
          </Button>
          <Button icon="check" onClick={submit} loading={mutation.isPending} loadingText="Creating…">
            Create task
          </Button>
        </>
      }
    >
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Field label="Title" required error={submitted ? errors.title : undefined}>
          <Input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} maxLength={200} autoFocus placeholder="e.g. Count empties at the godown" />
        </Field>
        <Field label="Description" optional>
          <Textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} rows={3} maxLength={5000} />
        </Field>
        <div className="grid-2">
          <Field label="Priority" required>
            <Select value={form.priority} onChange={(event) => setForm({ ...form, priority: event.target.value as TaskPriority })} options={priorityOptions} />
          </Field>
          <Field label="Category" optional>
            <Select value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value as TaskCategory })} options={TASK_CATEGORIES} />
          </Field>
          <Field label="Due date" required error={submitted ? errors.dueDate : undefined}>
            <Input type="date" min={todayInputValue()} value={form.dueDate} onChange={(event) => setForm({ ...form, dueDate: event.target.value })} />
          </Field>
          <Field label="Due time" optional>
            <Input type="time" value={form.dueTime} onChange={(event) => setForm({ ...form, dueTime: event.target.value })} />
          </Field>
        </div>
        <Field label={`Assign to${form.assignees.length ? ` (${form.assignees.length})` : ""}`} required error={submitted ? errors.assignees : undefined}>
          {teamLoading ? (
            <LoadingSkeleton rows={3} label="Loading team" />
          ) : team.length === 0 ? (
            <Alert tone="info">This merchant has no active staff to assign yet.</Alert>
          ) : (
            <div className="grid-2" style={{ maxHeight: 220, overflowY: "auto" }}>
              {team.map((member) => (
                <Checkbox
                  key={member.id}
                  checked={form.assignees.includes(member.id)}
                  onChange={() => toggle(member.id)}
                  label={member.name}
                  description={[roleLabel(member.role), member.branchName].filter(Boolean).join(" · ")}
                />
              ))}
            </div>
          )}
        </Field>
        {mutation.error ? <Alert tone="error">{normalizeError(mutation.error).userMessage}</Alert> : null}
      </form>
    </Modal>
  );
}

export default AdminTasksPage;
