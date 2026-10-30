import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  listCustomerTypes,
  listCylinderTypes,
  listKycDocumentTypes,
  updateCustomerType,
  updateCylinderType,
  updateKycDocumentType,
  type CustomerType,
  type CylinderType,
  type KycDocumentType
} from "../../api/catalogue.api";
import { queryKeys } from "../../api/query-keys";
import { useOptionalAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { Badge } from "../../components/common/StatusBadge";
import { ConfirmationDialog } from "../../components/feedback/Dialogs";
import { EmptyState, InlineError, RefreshIndicator } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Card, PageHeader, StatCard } from "../../components/layout/Page";
import { DataTable, TableHeader, type Column } from "../../components/tables/DataTable";
import { useUrlFilters } from "../../hooks/useUrlFilters";
import { formatNumber } from "../../utils/format";
import { CustomerTypeDialog, CylinderTypeDialog, KycDocumentTypeDialog } from "./CatalogueDialogs";
import { CustomerTypeRules } from "./CustomerTypeRules";

/**
 * The business catalogue: cylinder sizes, customer types and KYC document types.
 *
 * These used to be hardcoded in the apps, so adding a cylinder size meant a release. They are
 * rows now, and this is where they are maintained.
 *
 * Platform-wide, not per agency - a 19 KG cylinder is the same cylinder everywhere - so there
 * is no merchant picker here.
 *
 * Nothing is deleted. Retiring a row keeps every order, invoice and stock movement that names
 * it readable; a row the platform itself depends on cannot be retired at all.
 */

const FILTERS = ["tab", "show"] as const;

const TABS = [
  { value: "", label: "Cylinder types" },
  { value: "customers", label: "Customer types" },
  { value: "documents", label: "KYC documents" },
  { value: "rules", label: "Rules" }
];

const LIST_PARAMS = { includeInactive: true };

type Retiring =
  | { kind: "cylinder"; row: CylinderType }
  | { kind: "customer"; row: CustomerType }
  | { kind: "document"; row: KycDocumentType }
  | null;

export function AdminCataloguePage() {
  const auth = useOptionalAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { values, setFilter } = useUrlFilters(FILTERS);
  const tab = values.tab;
  const showRetired = values.show === "retired";

  const canManage = auth?.can(PERMISSIONS.catalogueManage) ?? false;

  const [editingCylinder, setEditingCylinder] = useState<CylinderType | "new" | null>(null);
  const [editingCustomer, setEditingCustomer] = useState<CustomerType | "new" | null>(null);
  const [editingDocument, setEditingDocument] = useState<KycDocumentType | "new" | null>(null);
  const [retiring, setRetiring] = useState<Retiring>(null);

  const cylinders = useQuery({
    queryKey: queryKeys.catalogue.cylinderTypes(LIST_PARAMS),
    queryFn: ({ signal }) => listCylinderTypes(LIST_PARAMS, signal),
    placeholderData: keepPreviousData
  });
  const customers = useQuery({
    queryKey: queryKeys.catalogue.customerTypes(LIST_PARAMS),
    queryFn: ({ signal }) => listCustomerTypes(LIST_PARAMS, signal),
    placeholderData: keepPreviousData
  });
  const documents = useQuery({
    queryKey: queryKeys.catalogue.kycDocumentTypes(LIST_PARAMS),
    queryFn: ({ signal }) => listKycDocumentTypes(LIST_PARAMS, signal),
    placeholderData: keepPreviousData
  });

  const active = tab === "customers" ? customers : tab === "documents" ? documents : cylinders;

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.catalogue.all });
  }

  /** Rows for the tab being shown, filtered by the In use / Retired toggle. */
  function visible<T extends { isActive: boolean }>(rows: T[] | undefined): T[] | undefined {
    if (!rows) return undefined;
    return rows.filter((row) => (showRetired ? !row.isActive : row.isActive));
  }

  function statusCell(row: { isActive: boolean; isProtected: boolean }) {
    if (!row.isActive) return <Badge tone="neutral">Retired</Badge>;
    return row.isProtected ? <Badge tone="info">Built in</Badge> : <Badge tone="success">In use</Badge>;
  }

  /**
   * A protected row has no retire action at all, rather than one that fails: the platform reads
   * it directly, so there is no state in which retiring it would be allowed.
   */
  function rowActions<T extends { isActive: boolean; isProtected: boolean }>(
    row: T,
    onEdit: () => void,
    onRetire: () => void
  ) {
    if (!canManage) return [];
    const actions = [{ label: "Edit details", icon: "edit" as const, onSelect: onEdit }];
    if (row.isProtected) return actions;
    return [
      ...actions,
      row.isActive
        ? { label: "Retire", icon: "ban" as const, danger: true, onSelect: onRetire }
        : { label: "Put back in use", icon: "refresh" as const, onSelect: onRetire }
    ];
  }

  const cylinderColumns: Column<CylinderType>[] = [
    {
      key: "label",
      header: "Cylinder",
      primary: true,
      sortValue: (row) => row.sortOrder,
      render: (row) => (
        <div className="cell-stack">
          <button type="button" className="btn--link cell-primary__title nowrap" onClick={() => setEditingCylinder(row)}>
            {row.label}
          </button>
          <small className="mono nowrap">{row.code}</small>
        </div>
      )
    },
    { key: "weight", header: "Weight", sortValue: (row) => row.weightKg, render: (row) => <span className="nowrap">{row.weightKg} kg</span> },
    { key: "variant", header: "Variant", render: (row) => <span className={row.variant ? undefined : "text-muted"}>{row.variant || "—"}</span> },
    {
      key: "price",
      header: "Default price",
      sortValue: (row) => row.defaultUnitPrice,
      render: (row) => (
        <div className="cell-stack">
          <span className="nowrap">₹{row.defaultUnitPrice}</span>
          <small className="nowrap text-muted">
            ₹{row.defaultBaseRate} + ₹{row.defaultMarkup}
          </small>
        </div>
      )
    },
    { key: "gst", header: "GST", render: (row) => <span className="nowrap">{row.gstPercent}%</span> },
    { key: "status", header: "Status", sortValue: (row) => (row.isActive ? 0 : 1), render: statusCell }
  ];

  const customerColumns: Column<CustomerType>[] = [
    {
      key: "label",
      header: "Customer type",
      primary: true,
      sortValue: (row) => row.sortOrder,
      render: (row) => (
        <div className="cell-stack">
          <button type="button" className="btn--link cell-primary__title nowrap" onClick={() => setEditingCustomer(row)}>
            {row.label}
          </button>
          <small className="mono nowrap">{row.code}</small>
        </div>
      )
    },
    { key: "prefix", header: "Code prefix", render: (row) => <span className="mono nowrap">{row.codePrefix}</span> },
    {
      key: "rules",
      header: "Requires",
      render: (row) => {
        const needs = [row.requiresDeliverySites ? "Delivery site" : null, row.requiresGstInvoice ? "GST invoice" : null].filter(Boolean);
        return <span className={needs.length ? undefined : "text-muted"}>{needs.length ? needs.join(", ") : "—"}</span>;
      }
    },
    { key: "default", header: "Default", render: (row) => (row.isDefault ? <Badge tone="info">Default</Badge> : <span className="text-muted">—</span>) },
    { key: "status", header: "Status", sortValue: (row) => (row.isActive ? 0 : 1), render: statusCell }
  ];

  const documentColumns: Column<KycDocumentType>[] = [
    {
      key: "label",
      header: "Document",
      primary: true,
      sortValue: (row) => row.sortOrder,
      render: (row) => (
        <div className="cell-stack">
          <button type="button" className="btn--link cell-primary__title nowrap" onClick={() => setEditingDocument(row)}>
            {row.label}
          </button>
          <small className="mono nowrap">{row.code}</small>
        </div>
      )
    },
    {
      key: "length",
      header: "Number length",
      render: (row) => {
        if (!row.minLength && !row.maxLength) return <span className="text-muted">Any</span>;
        if (row.minLength && row.maxLength && row.minLength === row.maxLength) return <span className="nowrap">{row.minLength}</span>;
        return <span className="nowrap">{`${row.minLength ?? "—"} to ${row.maxLength ?? "—"}`}</span>;
      }
    },
    { key: "expiry", header: "Expiry", render: (row) => (row.expiryRequired ? "Required" : <span className="text-muted">—</span>) },
    { key: "scan", header: "Scan", render: (row) => (row.scanRequired ? "Required" : <span className="text-muted">—</span>) },
    { key: "status", header: "Status", sortValue: (row) => (row.isActive ? 0 : 1), render: statusCell }
  ];

  const rows = tab === "customers" ? visible(customers.data) : tab === "documents" ? visible(documents.data) : visible(cylinders.data);
  const addLabel = tab === "customers" ? "Add customer type" : tab === "documents" ? "Add document type" : "Add cylinder type";

  function openNew() {
    if (tab === "customers") setEditingCustomer("new");
    else if (tab === "documents") setEditingDocument("new");
    else setEditingCylinder("new");
  }

  async function confirmRetire() {
    if (!retiring) return;
    const { kind, row } = retiring;
    const next = !row.isActive;
    if (kind === "cylinder") await updateCylinderType(row.code, { isActive: next });
    else if (kind === "customer") await updateCustomerType(row.code, { isActive: next });
    else await updateKycDocumentType(row.code, { isActive: next });
    toast.success(next ? `${row.label} is back in use.` : `${row.label} retired.`);
    invalidate();
  }

  return (
    <div className="page admin-catalogue-page">
      <PageHeader
        title="Business Catalogue"
        documentTitle="Business Catalogue"
        description="Cylinder sizes, customer types and KYC documents. These used to need a release to change; they are rows now."
        meta={<RefreshIndicator active={active.isFetching && !active.isLoading} />}
        actions={
          canManage && tab !== "rules" ? (
            <Button icon="plus" onClick={openNew}>
              {addLabel}
            </Button>
          ) : null
        }
      />

      {tab === "rules" ? <CustomerTypeRules /> : <>
      <div className="kpi-grid" aria-label="Catalogue summary">
        <StatCard
          label="Cylinder types"
          icon="box"
          tone="blue"
          value={cylinders.data ? formatNumber(cylinders.data.filter((row) => row.isActive).length) : "—"}
          hint="On the price card"
        />
        <StatCard
          label="Customer types"
          icon="users"
          tone="green"
          value={customers.data ? formatNumber(customers.data.filter((row) => row.isActive).length) : "—"}
          hint="Decide what may be ordered"
        />
        <StatCard
          label="KYC documents"
          icon="idCard"
          tone="slate"
          value={documents.data ? formatNumber(documents.data.filter((row) => row.isActive).length) : "—"}
          hint="Can be asked for at sign-up"
        />
      </div>

      <Card bodyless className="table-card">
        <div className="status-tabs status-tabs--card" role="tablist" aria-label="Catalogue section">
          {TABS.map((item) => (
            <button key={item.label} type="button" role="tab" aria-selected={tab === item.value} onClick={() => setFilter("tab", item.value)}>
              {item.label}
            </button>
          ))}
        </div>

        <TableHeader
          title={TABS.find((item) => item.value === tab)?.label ?? "Cylinder types"}
          count={rows?.length ?? 0}
          description={
            showRetired
              ? "Retired rows. Old orders and invoices still read correctly because nothing is deleted."
              : "In use now. Retiring a row hides it from new orders without touching the old ones."
          }
          actions={
            <Button variant="secondary" onClick={() => setFilter("show", showRetired ? "" : "retired")}>
              {showRetired ? "Show in use" : "Show retired"}
            </Button>
          }
        />

        {active.error && active.data ? (
          <div style={{ padding: "var(--space-4)" }}>
            <InlineError error={active.error} title="The list could not be refreshed" onRetry={() => void active.refetch()} />
          </div>
        ) : null}

        {tab === "customers" ? (
          <DataTable
            caption="Customer types"
            columns={customerColumns}
            rows={customers.data ? (rows as CustomerType[]) : undefined}
            getRowKey={(row) => row.code}
            onRowClick={(row) => setEditingCustomer(row)}
            rowLabel={(row) => row.label}
            rowActions={(row) => rowActions(row, () => setEditingCustomer(row), () => setRetiring({ kind: "customer", row }))}
            isLoading={customers.isLoading}
            error={customers.data ? undefined : customers.error}
            onRetry={() => void customers.refetch()}
            empty={<EmptyState icon="users" title={showRetired ? "Nothing retired" : "No customer types"} description="Customer types decide what a customer may order." />}
          />
        ) : tab === "documents" ? (
          <DataTable
            caption="KYC document types"
            columns={documentColumns}
            rows={documents.data ? (rows as KycDocumentType[]) : undefined}
            getRowKey={(row) => row.code}
            onRowClick={(row) => setEditingDocument(row)}
            rowLabel={(row) => row.label}
            rowActions={(row) => rowActions(row, () => setEditingDocument(row), () => setRetiring({ kind: "document", row }))}
            isLoading={documents.isLoading}
            error={documents.data ? undefined : documents.error}
            onRetry={() => void documents.refetch()}
            empty={<EmptyState icon="idCard" title={showRetired ? "Nothing retired" : "No document types"} description="Document types are what a customer can be asked to produce." />}
          />
        ) : (
          <DataTable
            caption="Cylinder types"
            columns={cylinderColumns}
            rows={cylinders.data ? (rows as CylinderType[]) : undefined}
            getRowKey={(row) => row.code}
            onRowClick={(row) => setEditingCylinder(row)}
            rowLabel={(row) => row.label}
            rowActions={(row) => rowActions(row, () => setEditingCylinder(row), () => setRetiring({ kind: "cylinder", row }))}
            isLoading={cylinders.isLoading}
            error={cylinders.data ? undefined : cylinders.error}
            onRetry={() => void cylinders.refetch()}
            empty={
              <EmptyState
                icon="box"
                title={showRetired ? "Nothing retired" : "No cylinder types"}
                description="Add a size to put it on the price card."
                action={canManage && !showRetired ? <Button icon="plus" onClick={() => setEditingCylinder("new")}>Add cylinder type</Button> : undefined}
              />
            }
          />
        )}
      </Card>
      </>}

      <CylinderTypeDialog
        item={editingCylinder}
        onClose={() => setEditingCylinder(null)}
        onSaved={(saved, created) => {
          toast.success(created ? `${saved.label} added.` : `${saved.label} updated.`);
          invalidate();
        }}
      />
      <CustomerTypeDialog
        item={editingCustomer}
        onClose={() => setEditingCustomer(null)}
        onSaved={(saved, created) => {
          toast.success(created ? `${saved.label} added.` : `${saved.label} updated.`);
          invalidate();
        }}
      />
      <KycDocumentTypeDialog
        item={editingDocument}
        onClose={() => setEditingDocument(null)}
        onSaved={(saved, created) => {
          toast.success(created ? `${saved.label} added.` : `${saved.label} updated.`);
          invalidate();
        }}
      />

      <ConfirmationDialog
        open={retiring !== null}
        title={retiring?.row.isActive ? `Retire ${retiring.row.label}?` : `Put ${retiring?.row.label ?? "this row"} back in use?`}
        description={
          retiring?.row.isActive
            ? "It stops being offered on new orders. Everything already placed keeps naming it and keeps reading correctly."
            : "It becomes available again straight away."
        }
        confirmLabel={retiring?.row.isActive ? "Retire" : "Put back in use"}
        confirmVariant={retiring?.row.isActive ? "danger" : "primary"}
        onClose={() => setRetiring(null)}
        onConfirm={confirmRetire}
      />
    </div>
  );
}

export default AdminCataloguePage;
