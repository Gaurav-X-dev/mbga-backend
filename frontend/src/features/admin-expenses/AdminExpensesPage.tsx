import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { expenseToday, expenseMonth, fuelMileage } from "./expense-utils";
import { normalizeError } from "../../api/errors";
import {
  getExpenseFuelOptions, uploadExpenseReceipt, downloadExpenseReceipt,
  createExpense,
  createExpenseCategory,
  deleteExpense,
  getExpenseBreakdown,
  listExpenseCategories,
  listExpensePeriods,
  listExpenses,
  updateExpense,
  updateExpenseCategory,
  type Expense,
  type ExpenseCategory,
  type ExpenseInput
} from "../../api/expenses.api";
import { listMerchants } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { useOptionalAuth } from "../../auth/auth-context";
import { Button, IconButton } from "../../components/common/Button";
import { Icon, type IconName } from "../../components/common/Icon";
import { Badge } from "../../components/common/StatusBadge";
import { ConfirmationDialog, Modal } from "../../components/feedback/Dialogs";
import { Alert, EmptyState, InlineError, LoadingSkeleton, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Input, SearchInput, Select, Textarea } from "../../components/forms/Field";
import { Card, PageHeader, StatCard } from "../../components/layout/Page";
import { DataTable, FilterBar, Pagination, TableHeader, type Column } from "../../components/tables/DataTable";
import { useSearchFilter, useUrlFilters } from "../../hooks/useUrlFilters";
import { formatCurrency, formatDate, formatDateTime, formatNumber } from "../../utils/format";

const PAGE_SIZE = 20;
const FILTERS = ["merchant", "period", "category", "search", "from", "to"] as const;

/** The backend accepts only these icon keys; each maps to one the panel can draw. */
const CATEGORY_ICONS: Array<{ value: string; label: string; icon: IconName }> = [
  { value: "fuel", label: "Fuel", icon: "flame" },
  { value: "maintenance", label: "Maintenance", icon: "settings" },
  { value: "salary", label: "Salary", icon: "users" },
  { value: "rent", label: "Rent", icon: "store" },
  { value: "utilities", label: "Utilities", icon: "zap" },
  { value: "misc", label: "Miscellaneous", icon: "box" }
];

function categoryIcon(icon: string): IconName {
  return CATEGORY_ICONS.find((item) => item.value === icon)?.icon ?? "box";
}

const BAR_COLORS = ["#3b82f6", "#f97316", "#16a34a", "#8b5cf6", "#eab308", "#ef4444", "#14b8a6", "#64748b"];

export interface AdminExpensesPageProps {
  merchantId?: string;
  isMerchantPanel?: boolean;
  title?: string;
}

export function AdminExpensesPage({ merchantId: propMerchantId, isMerchantPanel = false, title = "Expenses" }: AdminExpensesPageProps = {}) {
  const auth = useOptionalAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { values, page, setFilter, setPage, clearFilters, hasFilters } = useUrlFilters(FILTERS);
  const [searchText, setSearchText] = useSearchFilter(values.search, (value) => setFilter("search", value));
  const merchantId = propMerchantId || (isMerchantPanel ? (auth?.user?.merchant as any)?.id || "" : values.merchant);
  const selectedPeriod = values.period || "CURRENT";
  const period = selectedPeriod === "CURRENT" ? expenseMonth() : selectedPeriod === "LAST" ? expenseMonth(-1) : selectedPeriod === "CUSTOM" ? "ALL" : selectedPeriod;
  const range = selectedPeriod === "CUSTOM" ? { from: values.from, to: values.to } : {};
  const invalidRange = selectedPeriod === "CUSTOM" && (!values.from || !values.to || values.from > values.to || (Date.parse(values.to) - Date.parse(values.from)) / 86400000 > 366);
  const canManage = auth ? auth.can("expenses.manage") : true;

  const [editing, setEditing] = useState<Expense | "new" | null>(null);
  const [deleting, setDeleting] = useState<Expense | null>(null);
  const [managingCategories, setManagingCategories] = useState(false);

  const merchantParams = { limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: queryKeys.merchants.list(merchantParams),
    queryFn: ({ signal }) => listMerchants(merchantParams, signal),
    enabled: !isMerchantPanel,
    staleTime: 5 * 60_000
  });

  // Expenses are kept per merchant, so open on the first one rather than an empty screen.
  useEffect(() => {
    if (isMerchantPanel) return;
    const first = merchants.data?.items[0];
    if (!values.merchant && first) setFilter("merchant", first.id);
  }, [isMerchantPanel, values.merchant, merchants.data, setFilter]);

  const enabled = Boolean(merchantId);
  const periods = useQuery({
    queryKey: queryKeys.expenses.periods(merchantId),
    queryFn: ({ signal }) => listExpensePeriods(merchantId, signal),
    enabled
  });
  const categories = useQuery({
    queryKey: queryKeys.expenses.categories(merchantId, false),
    queryFn: ({ signal }) => listExpenseCategories(merchantId, false, signal),
    enabled,
    staleTime: 5 * 60_000
  });
  const breakdown = useQuery({
    queryKey: [...queryKeys.expenses.breakdown(merchantId, period), range],
    queryFn: ({ signal }) => getExpenseBreakdown(merchantId, period, signal, range),
    enabled: enabled && !invalidRange
  });
  const monthSummary = useQuery({
    queryKey: queryKeys.expenses.breakdown(merchantId, expenseMonth()),
    queryFn: ({ signal }) => getExpenseBreakdown(merchantId, expenseMonth(), signal), enabled
  });
  const params = {
    ...range,
    merchantId,
    period,
    categoryId: values.category || undefined,
    search: values.search || undefined,
    page,
    pageSize: PAGE_SIZE
  };
  const list = useQuery({
    queryKey: queryKeys.expenses.list(params),
    queryFn: ({ signal }) => listExpenses(params, signal),
    enabled: enabled && !invalidRange,
    placeholderData: keepPreviousData
  });

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.expenses.all });
  }

  const summary = list.data?.summary;
  const fuelSpend = breakdown.data?.categories?.filter((item) => item.code === "FUEL" || item.icon === "fuel").reduce((total, item) => total + item.totalAmount, 0) ?? 0;
  const periodLabel = selectedPeriod === "CUSTOM" ? `${values.from || "From"} – ${values.to || "To"}` : period === "ALL" ? "All periods" : (periods.data?.find((item) => item.period === period)?.label ?? period);

  const columns: Column<Expense>[] = [
    {
      key: "date",
      header: "Date",
      sortValue: (row) => row.date,
      render: (row) => (
        <div className="cell-stack">
          <span className="nowrap">{formatDate(row.date)}</span>
          <small className="nowrap">{row.periodLabel}</small>
        </div>
      )
    },
    {
      key: "category",
      header: "Category",
      primary: true,
      sortValue: (row) => row.category.label,
      render: (row) => (
        <span className="row nowrap" style={{ gap: 8, flexWrap: "nowrap" }}>
          <span className="mini-stat__icon tone-blue" aria-hidden="true">
            <Icon name={categoryIcon(row.category.icon)} size={14} />
          </span>
          <button type="button" className="btn--link cell-primary__title" disabled={!canManage} onClick={() => setEditing(row)}>
            {row.category.label}
          </button>
        </span>
      )
    },
    {
      key: "note",
      header: "Note",
      render: (row) => (
        <span
          title={row.note ?? undefined}
          style={{ display: "block", maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
          className={row.note ? undefined : "text-muted"}
        >
          {row.note || "—"}
        </span>
      )
    },
    {
      key: "fuel", header: "Fuel details",
      render: (row) => <div className="stack" style={{gap: 4}}>
        <div className="row" style={{gap: 4}}>
          {row.vehicleNumber ? <Badge>🚗 {row.vehicleNumber}</Badge> : null}
          {row.fuelType ? <Badge>⛽ {row.fuelType}</Badge> : null}
          {row.mileage != null ? <Badge>📊 {row.mileage.toFixed(2)} km/L</Badge> : null}
        </div>
        {row.driverName ? <small>{row.driverName}</small> : null}
        {row.hasReceipt ? <Button variant="link" onClick={(event) => {
          event.stopPropagation();
          void downloadExpenseReceipt(merchantId, row.id).catch((error) => toast.error(normalizeError(error).userMessage));
        }}>Receipt</Button> : null}
      </div>
    },
    {
      key: "amount",
      header: "Amount",
      align: "right",
      sortValue: (row) => row.amount,
      render: (row) => <strong className="nowrap">{formatCurrency(row.amount)}</strong>
    },
    {
      key: "recorded",
      header: "Recorded by",
      hideOnMobile: true,
      render: (row) => (
        <div className="cell-stack" title={formatDateTime(row.createdAt)}>
          <span className="nowrap">{row.recordedBy}</span>
          <small className="nowrap">{formatDate(row.createdAt)}</small>
        </div>
      )
    }
  ];

  return (
    <div className="page admin-expenses-page">
      <PageHeader
        title={title}
        documentTitle={title}
        description={isMerchantPanel ? "Track spend on fuel, vehicles, salaries and running costs." : "Track what each merchant spends on fuel, vehicles, salaries and running costs."}
        meta={<RefreshIndicator active={list.isFetching && !list.isLoading} />}
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
            {(!auth || auth.can("reports.view")) && merchantId ? <Link className="btn btn--secondary" to={`${isMerchantPanel ? "/merchant" : "/admin"}/reports?type=FUEL&merchant=${encodeURIComponent(merchantId)}`}>Fuel report</Link> : null}
            <Button variant="secondary" icon="settings" onClick={() => setManagingCategories(true)} disabled={!enabled || !canManage}>
              Categories
            </Button>
            <Button icon="plus" onClick={() => setEditing("new")} disabled={!enabled || !canManage}>
              Add expense
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
            <EmptyState icon="store" title="Choose a merchant" description="Expenses are kept per merchant. Pick one above to see its spend." />
          </Card>
        )
      ) : (
        <>
          <div className="row" style={{alignItems: "flex-end"}}>
            <Field label="Period">
              <Select value={selectedPeriod} onChange={(event) => setFilter("period", event.target.value)} options={[
                {value:"CURRENT", label:"Current Month"}, {value:"LAST", label:"Last Month"},
                {value:"CUSTOM", label:"Custom Date Range"}, {value:"ALL", label:"All Periods"},
                ...(periods.data ?? []).filter((p) => ![expenseMonth(), expenseMonth(-1)].includes(p.period)).map((p) => ({value:p.period,label:p.label}))
              ]} />
            </Field>
            {selectedPeriod === "CUSTOM" ? <>
              <Field label="From"><Input type="date" value={values.from} max={values.to || expenseToday()} onChange={(e) => setFilter("from",e.target.value)} /></Field>
              <Field label="To"><Input type="date" value={values.to} min={values.from || undefined} max={expenseToday()} onChange={(e) => setFilter("to",e.target.value)} /></Field>
            </> : null}
          </div>
          {invalidRange ? <Alert tone="warning">Choose both dates in order, with a range of no more than one year.</Alert> : null}
          <div className="kpi-grid" aria-label="Expense summary">
            <StatCard label="Current Month Spend" icon="wallet" tone="orange" value={monthSummary.data ? formatCurrency(monthSummary.data.totalAmount) : "—"} hint={expenseMonth()} />
            <StatCard label="Fuel Spend" icon="flame" tone="orange" value={invalidRange ? "—" : formatCurrency(fuelSpend)} hint={periodLabel} />
            <StatCard label="Total Entries" icon="fileText" tone="blue" value={invalidRange ? "—" : formatNumber(breakdown.data?.entryCount)} hint={periodLabel} />
          </div>
          {monthSummary.error ? <InlineError error={monthSummary.error} title="Monthly spend could not be loaded" onRetry={() => void monthSummary.refetch()} /> : null}
          <div className="grid-sidebar" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 360px), 1fr))", gap: "var(--space-5)", alignItems: "start" }}>
            <Card bodyless className="table-card">
              <TableHeader
                title="Expenses"
                count={list.data?.total}
                description={
                  summary && hasFilters
                    ? `${formatCurrency(summary.totalAmount)} across ${formatNumber(summary.entryCount)} matching entries`
                    : "Newest spend first."
                }
              />
              <FilterBar
                onReset={() => clearFilters(["category", "search"])}
                canReset={Boolean(values.category || values.search)}
              >
                <SearchInput
                  label="Search expenses"
                  placeholder="Vehicle, driver, note or category"
                  value={searchText}
                  onChange={(event) => setSearchText(event.target.value)}
                />
                <Field label="Category" hideLabel>
                  <Select
                    value={values.category}
                    onChange={(event) => setFilter("category", event.target.value)}
                    placeholder="All categories"
                    options={(categories.data ?? []).map((item) => ({ value: item.id, label: item.label }))}
                  />
                </Field>
              </FilterBar>

              {list.error && list.data ? (
                <div style={{ padding: "var(--space-4)" }}>
                  <InlineError error={list.error} title="The list could not be refreshed" onRetry={() => void list.refetch()} />
                </div>
              ) : null}

              <DataTable
                caption="Expenses"
                columns={columns}
                rows={invalidRange ? [] : list.data?.items}
                getRowKey={(row) => row.id}
                onRowClick={canManage ? (row) => setEditing(row) : undefined}
                rowLabel={(row) => `${row.category.label} ${formatCurrency(row.amount)}`}
                rowActions={(row) => canManage ? [
                  { label: "Edit", icon: "edit", onSelect: () => setEditing(row) },
                  { label: "Delete", icon: "trash", danger: true, onSelect: () => setDeleting(row) }
                ] : []}
                isLoading={list.isLoading}
                error={list.data ? undefined : list.error}
                onRetry={() => void list.refetch()}
                empty={
                  values.category || values.search ? (
                    <EmptyState icon="search" title="No expenses match" description="Try a different category or search." />
                  ) : (
                    <EmptyState
                      icon="wallet"
                      title="No expenses in this period"
                      description="Add fuel, maintenance, salary and other spend as it happens."
                      action={<Button icon="plus" onClick={() => setEditing("new")} disabled={!canManage}>Add expense</Button>}
                    />
                  )
                }
                footer={
                  <Pagination
                    page={page}
                    pageSize={PAGE_SIZE}
                    total={list.data?.total ?? 0}
                    onPageChange={setPage}
                    itemLabel="expenses"
                    disabled={list.isFetching}
                  />
                }
              />
            </Card>

            <Card title="Spend by category" subtitle={periodLabel}>
              {breakdown.isLoading ? (
                <LoadingSkeleton rows={4} label="Loading breakdown" />
              ) : breakdown.error ? (
                <InlineError error={breakdown.error} onRetry={() => void breakdown.refetch()} />
              ) : !breakdown.data?.categories?.length ? (
                <EmptyState icon="chart" title="Nothing spent yet" description="The split appears once expenses are filed." />
              ) : (
                <ul className="list-plain stack" aria-label="Spend by category">
                  {breakdown.data.categories.map((item, index) => (
                    <li key={item.categoryId}>
                      <button
                        type="button"
                        className="btn--link"
                        style={{ width: "100%", textAlign: "left", display: "block" }}
                        onClick={() => setFilter("category", values.category === item.categoryId ? "" : item.categoryId)}
                        aria-pressed={values.category === item.categoryId}
                        title="Filter the list by this category"
                      >
                        <span className="row-between" style={{ gap: 8 }}>
                          <span className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
                            <Icon name={categoryIcon(item.icon)} size={14} />
                            <strong>{item.label}</strong>
                          </span>
                          <span className="nowrap">{formatCurrency(item.totalAmount)}</span>
                        </span>
                        <span style={{ display: "block", height: 6, borderRadius: 999, background: "var(--border)", margin: "6px 0 2px" }}>
                          <span
                            style={{
                              display: "block",
                              height: "100%",
                              width: `${Math.max(item.sharePercent, 1)}%`,
                              borderRadius: 999,
                              background: BAR_COLORS[index % BAR_COLORS.length]
                            }}
                          />
                        </span>
                        <small className="text-muted">
                          {item.sharePercent.toFixed(1)}% · {formatNumber(item.entryCount)} {item.entryCount === 1 ? "entry" : "entries"}
                        </small>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </>
      )}

      <ExpenseDialog
        merchantId={merchantId}
        expense={editing}
        categories={categories.data ?? []}
        onClose={() => setEditing(null)}
        onSaved={(created) => {
          toast.success(created ? "Expense added." : "Expense updated.");
          invalidate();
        }}
      />

      <ConfirmationDialog
        open={deleting !== null}
        title="Delete this expense?"
        description={
          deleting ? `${deleting.category.label} of ${formatCurrency(deleting.amount)} on ${formatDate(deleting.date)} will be removed permanently.` : ""
        }
        confirmLabel="Delete expense"
        onClose={() => setDeleting(null)}
        onConfirm={async () => {
          if (!deleting) return;
          await deleteExpense(merchantId, deleting.id);
          toast.success("Expense deleted.");
          invalidate();
        }}
      />

      <CategoriesDialog merchantId={merchantId} open={managingCategories} onClose={() => setManagingCategories(false)} onChanged={invalidate} />
    </div>
  );
}

function ExpenseDialog({
  merchantId,
  expense,
  categories,
  onClose,
  onSaved
}: {
  merchantId: string;
  expense: Expense | "new" | null;
  categories: ExpenseCategory[];
  onClose: () => void;
  onSaved: (created: boolean) => void;
}) {
  const open = expense !== null;
  const existing = expense && expense !== "new" ? expense : null;
  const emptyFuel = {destination: "", vehicleId: "", driverId: "", fuelType: "", kmReading: "", distance: "", liters: ""};
  const [form, setForm] = useState({ categoryId: "", amount: "", date: "", note: "", ...emptyFuel });
  const [fuelEnabled, setFuelEnabled] = useState(true);
  const [receipt, setReceipt] = useState<File | null>(null);
  const [savedExpenseId, setSavedExpenseId] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const fuelCategory = categories.find((category) => category.id === form.categoryId) ?? (existing?.category.id === form.categoryId ? existing.category : null);
  const isFuel = fuelCategory?.code === "FUEL" || fuelCategory?.icon === "fuel";
  const fuelOptions = useQuery({ queryKey: ["expense-fuel-options", merchantId],
    queryFn: ({signal}) => getExpenseFuelOptions(merchantId, signal), enabled: open && isFuel });
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (!open) return;
    setSubmitted(false);
    setFuelEnabled(!existing || Boolean(existing.vehicleId));
    setReceipt(null);
    setSavedExpenseId(null);
    setForm(
      existing
        ? { categoryId: existing.category.id, amount: String(existing.amount), date: existing.date, note: existing.note ?? "", destination: existing.destination ?? "", vehicleId: existing.vehicleId ?? "", driverId: existing.driverId ?? "", fuelType: existing.fuelType ?? "", kmReading: existing.kmReading == null ? "" : String(existing.kmReading), distance: existing.distance == null ? "" : String(existing.distance), liters: existing.liters == null ? "" : String(existing.liters) }
        : { categoryId: "", amount: "", date: expenseToday(), note: "", ...emptyFuel }
    );
  }, [open, existing]);

  const mutation = useMutation({
    mutationFn: async (input: ExpenseInput) => {
      const id = existing?.id || savedExpenseId;
      const saved = id ? await updateExpense(merchantId, id, input) : await createExpense(merchantId, input);
      setSavedExpenseId(saved.id);
      if (receipt) await uploadExpenseReceipt(merchantId, saved.id, receipt);
      return saved;
    },
    onSettled: () => {
      void queryClient.invalidateQueries({queryKey: queryKeys.expenses.all});
      void queryClient.invalidateQueries({queryKey: ["admin", "audit-logs"]});
    },
    onSuccess: () => {
      onSaved(!existing);
      onClose();
    }
  });

  const amount = Number(form.amount);
  const errors = {
    categoryId: form.categoryId ? undefined : "Choose a category.",
    amount: amount > 0 ? undefined : "Enter an amount greater than 0.",
    fuel: isFuel && fuelEnabled && (!form.vehicleId || !form.driverId || !form.fuelType || !form.kmReading || !Number.isFinite(Number(form.kmReading)) || Number(form.kmReading) < 0 || !fuelMileage(form.distance, form.liters)) ? "Choose a vehicle and driver, and enter valid KM reading, distance and liters." : undefined,
    receipt: receipt && (receipt.size > 5 * 1024 * 1024 || !["image/jpeg", "image/png", "application/pdf"].includes(receipt.type)) ? "Choose a JPG, PNG or PDF up to 5 MB." : undefined,
    date: !form.date ? "Choose a date." : form.date > expenseToday() ? "An expense cannot be dated in the future." : undefined
  };
  const valid = !Object.values(errors).some(Boolean);

  function submit() {
    setSubmitted(true);
    if (!valid) return;
    // An emptied note is sent as "" so the server clears it on edit.
    mutation.mutate({ categoryId: form.categoryId, amount, date: form.date, note: existing ? form.note.trim() : form.note.trim() || undefined,
      ...(isFuel ? {destination: form.destination.trim()} : {}),
      ...(isFuel && fuelEnabled ? {vehicleId:form.vehicleId, driverId:form.driverId, fuelType:form.fuelType, kmReading:Number(form.kmReading), distance:Number(form.distance), liters:Number(form.liters)} : {})
    });
  }

  const set = (key: keyof typeof form) => (event: { target: { value: string } }) => setForm((previous) => ({ ...previous, [key]: event.target.value }));

  // A deactivated category stays selectable on the expense that already uses it.
  const options = categories.map((item) => ({ value: item.id, label: item.label }));
  if (existing && !categories.some((item) => item.id === existing.category.id)) {
    options.push({ value: existing.category.id, label: `${existing.category.label} (inactive)` });
  }

  return (
    <Modal
      open={open}
      title={existing ? "Edit expense" : "Add expense"}
      description={existing ? `Recorded by ${existing.recordedBy} on ${formatDateTime(existing.createdAt)}.` : "File one spend. It can be back-dated but not post-dated."}
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
          <Button icon="check" onClick={submit} loading={mutation.isPending} loadingText="Saving…">
            {existing ? "Save changes" : "Add expense"}
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
        <Field label="Category" required error={submitted ? errors.categoryId : undefined}>
          <Select value={form.categoryId} onChange={set("categoryId")} placeholder="Choose a category" options={options} />
        </Field>
        <div className="grid-2">
          <Field label="Amount (₹)" required error={submitted ? errors.amount : undefined}>
            <Input type="number" min={0} step="0.01" inputMode="decimal" value={form.amount} onChange={set("amount")} autoFocus={!existing} />
          </Field>
          <Field label="Date" required error={submitted ? errors.date : undefined}>
            <Input type="date" max={expenseToday()} value={form.date} onChange={set("date")} />
          </Field>
        </div>
        {isFuel && existing && !existing.vehicleId ? <label className="row"><input type="checkbox" checked={fuelEnabled} onChange={(e) => setFuelEnabled(e.target.checked)} />Add fuel details to this existing expense</label> : null}
        {isFuel && fuelEnabled ? <fieldset className="stack" disabled={mutation.isPending} style={{border:"1px solid var(--border)",borderRadius:12,padding:16}}>
          <legend>Fuel details</legend>
          <div className="grid-2">
            <Field label="Vehicle" required><Select value={form.vehicleId} onChange={set("vehicleId")} placeholder="Choose vehicle" options={[
              ...(fuelOptions.data?.vehicles ?? []), ...(existing?.vehicleId && !fuelOptions.data?.vehicles.some((v) => v.value === existing.vehicleId) ? [{value:existing.vehicleId,label:existing.vehicleNumber || "Recorded vehicle"}] : [])
            ]} /></Field>
            <Field label="Driver" required><Select value={form.driverId} onChange={set("driverId")} placeholder="Choose driver" options={[
              ...(fuelOptions.data?.drivers ?? []), ...(existing?.driverId && !fuelOptions.data?.drivers.some((d) => d.value === existing.driverId) ? [{value:existing.driverId,label:existing.driverName || "Recorded driver"}] : [])
            ]} /></Field>
            <Field label="Fuel type" required><Select value={form.fuelType} onChange={set("fuelType")} placeholder="Choose fuel type" options={[...(fuelOptions.data?.fuelTypes ?? []), ...(existing?.fuelType && !fuelOptions.data?.fuelTypes.some((item) => item.value === existing.fuelType) ? [{value:existing.fuelType,label:existing.fuelType}] : [])]} /></Field>
            <Field label="KM reading" required><Input type="number" min="0" step="0.01" value={form.kmReading} onChange={set("kmReading")} /></Field>
            <Field label="Distance (km)" required><Input type="number" min="0.01" step="0.01" value={form.distance} onChange={set("distance")} /></Field>
            <Field label="Liters" required><Input type="number" min="0.001" step="0.001" value={form.liters} onChange={set("liters")} /></Field>
          </div>
          <Field label="Destination" optional><Input value={form.destination} onChange={set("destination")} maxLength={160} placeholder="Route or destination" /></Field>
          <div className="card" style={{padding:12}} aria-live="polite">Avg: {fuelMileage(form.distance,form.liters)?.toFixed(2) ?? "—"} km/L</div>
          {submitted && errors.fuel ? <Alert tone="error">{errors.fuel}</Alert> : null}
          {fuelOptions.error ? <InlineError error={fuelOptions.error} title="Vehicles and drivers could not be loaded" onRetry={() => void fuelOptions.refetch()} /> : null}
        </fieldset> : null}
        <Field label="Receipt" optional hint={existing?.hasReceipt ? "Receipt already attached. Choose a file to replace it." : "JPG, PNG or PDF, up to 5 MB."} error={errors.receipt}>
          <Input type="file" accept="image/jpeg,image/png,application/pdf" onChange={(e) => setReceipt(e.target.files?.[0] ?? null)} disabled={mutation.isPending} />
        </Field>
        {savedExpenseId && mutation.error ? <Alert tone="warning">Expense saved. Retry to finish attaching the receipt.</Alert> : null}
        <Field label="Note" optional>
          <Textarea value={form.note} onChange={set("note")} rows={3} maxLength={255} placeholder="e.g. Diesel for GJ01AB1234" />
        </Field>
        {mutation.error ? <Alert tone="error">{normalizeError(mutation.error).userMessage}</Alert> : null}
      </form>
    </Modal>
  );
}

function CategoriesDialog({
  merchantId,
  open,
  onClose,
  onChanged
}: {
  merchantId: string;
  open: boolean;
  onClose: () => void;
  onChanged: () => void;
}) {
  const toast = useToast();
  const query = useQuery({
    queryKey: queryKeys.expenses.categories(merchantId, true),
    queryFn: ({ signal }) => listExpenseCategories(merchantId, true, signal),
    enabled: open && Boolean(merchantId)
  });
  const [draft, setDraft] = useState({ label: "", icon: "misc" });
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editLabel, setEditLabel] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setDraft({ label: "", icon: "misc" });
      setEditingId(null);
      setError(null);
    }
  }, [open]);

  function run<T>(action: () => Promise<T>, message: (result: T) => string) {
    setError(null);
    return action()
      .then((result) => {
        toast.success(message(result));
        onChanged();
      })
      .catch((caught) => setError(normalizeError(caught).userMessage));
  }

  const add = useMutation({
    mutationFn: () => createExpenseCategory(merchantId, { label: draft.label.trim(), icon: draft.icon }),
    onSuccess: (created) => {
      toast.success(`"${created.label}" added.`);
      setDraft({ label: "", icon: "misc" });
      setError(null);
      onChanged();
    },
    onError: (caught) => setError(normalizeError(caught).userMessage)
  });

  return (
    <Modal open={open} wide title="Expense categories" description="The list the Add-expense picker offers for this merchant." onClose={onClose}>
      <div className="stack">
        <form
          className="row"
          style={{ alignItems: "flex-end", gap: "var(--space-3)" }}
          onSubmit={(event) => {
            event.preventDefault();
            if (draft.label.trim()) add.mutate();
          }}
        >
          <Field label="New category">
            <Input value={draft.label} onChange={(event) => setDraft({ ...draft, label: event.target.value })} placeholder="e.g. Tolls" maxLength={60} />
          </Field>
          <Field label="Icon">
            <Select value={draft.icon} onChange={(event) => setDraft({ ...draft, icon: event.target.value })} options={CATEGORY_ICONS} />
          </Field>
          <Button type="submit" icon="plus" loading={add.isPending} disabled={!draft.label.trim()}>
            Add
          </Button>
        </form>

        {error ? <Alert tone="error">{error}</Alert> : null}

        {query.isLoading ? (
          <LoadingSkeleton rows={5} label="Loading categories" />
        ) : query.error ? (
          <InlineError error={query.error} onRetry={() => void query.refetch()} />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Category</th>
                  <th>Icon</th>
                  <th style={{ textAlign: "right" }}>Expenses</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(query.data ?? []).map((item) => (
                  <tr key={item.id}>
                    <td>
                      {editingId === item.id ? (
                        <form
                          className="row"
                          style={{ gap: 6, flexWrap: "nowrap" }}
                          onSubmit={(event) => {
                            event.preventDefault();
                            if (!editLabel.trim()) return;
                            void run(() => updateExpenseCategory(merchantId, item.id, { label: editLabel.trim() }), () => "Category renamed.").then(() =>
                              setEditingId(null)
                            );
                          }}
                        >
                          <Input value={editLabel} onChange={(event) => setEditLabel(event.target.value)} maxLength={60} autoFocus aria-label="Category name" />
                          <IconButton icon="check" label="Save name" type="submit" />
                          <IconButton icon="x" label="Cancel rename" onClick={() => setEditingId(null)} />
                        </form>
                      ) : (
                        <div className="cell-stack">
                          <strong>{item.label}</strong>
                          <small className="mono">{item.code}</small>
                        </div>
                      )}
                    </td>
                    <td>
                      <Select
                        className="select--sm"
                        aria-label={`Icon for ${item.label}`}
                        value={item.icon}
                        onChange={(event) =>
                          void run(() => updateExpenseCategory(merchantId, item.id, { icon: event.target.value }), () => "Icon updated.")
                        }
                        options={CATEGORY_ICONS}
                      />
                    </td>
                    <td style={{ textAlign: "right" }}>{formatNumber(item.expenseCount ?? 0)}</td>
                    <td>
                      {item.isActive ? <Badge tone="success">Active</Badge> : <Badge tone="neutral">Inactive</Badge>}
                      {item.isCustom ? null : (
                        <>
                          {" "}
                          <Badge tone="info">Default</Badge>
                        </>
                      )}
                    </td>
                    <td>
                      <span className="row" style={{ gap: 4, flexWrap: "nowrap", justifyContent: "flex-end" }}>
                        <IconButton
                          icon="edit"
                          label={`Rename ${item.label}`}
                          onClick={() => {
                            setEditingId(item.id);
                            setEditLabel(item.label);
                          }}
                        />
                        <IconButton
                          icon={item.isActive ? "ban" : "check"}
                          label={item.isActive ? `Deactivate ${item.label}` : `Activate ${item.label}`}
                          onClick={() =>
                            void run(
                              () => updateExpenseCategory(merchantId, item.id, { isActive: !item.isActive }),
                              () => (item.isActive ? `"${item.label}" deactivated.` : `"${item.label}" activated.`)
                            )
                          }
                        />
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="meta">An inactive category is hidden from the picker; expenses already filed under it keep its label.</p>
      </div>
    </Modal>
  );
}

export default AdminExpensesPage;
