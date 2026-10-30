import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { getCreditReport, type CustomerCredit } from "../../api/credit.api";
import { getCustomerEligibility, listCustomers, type Customer } from "../../api/customers.api";
import { normalizeError } from "../../api/errors";
import {
  createOrder,
  getRepeatPreview,
  listOrderCylinderTypes,
  quoteOrder,
  type Order,
  type OrderLine,
  type RepeatPreview,
} from "../../api/orders.api";
import { queryKeys } from "../../api/query-keys";
import { Button, IconButton } from "../../components/common/Button";
import { Icon } from "../../components/common/Icon";
import { Badge, StatusBadge, UserAvatar } from "../../components/common/StatusBadge";
import { Modal } from "../../components/feedback/Dialogs";
import { Alert, InlineError, LoadingSkeleton } from "../../components/feedback/Feedback";
import { Field, Input, SearchInput, Select } from "../../components/forms/Field";
import { DetailsPanel } from "../../components/layout/Page";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import { formatCurrency, formatDate, formatNumber, humanize } from "../../utils/format";
import { cylinderTypesFor } from "./order-constants";
import { formatAddress } from "./order-utils";

function newKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

const nameOf = (c: Pick<Customer, "businessName" | "ownerName" | "mobile">) =>
  c.businessName || c.ownerName || c.mobile;

interface Props {
  open: boolean;
  merchantId: string;
  onClose: () => void;
  onCreated: (order: Order) => void;
}

export function CreateOrderDialog({ open, merchantId, onClose, onCreated }: Props) {
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [search, setSearch] = useState("");
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [siteId, setSiteId] = useState("");
  const [orderMode, setOrderMode] = useState<"NEW" | "REPEAT">("NEW");
  const [idempotencyKey, setIdempotencyKey] = useState(newKey);
  const [repeatBanner, setRepeatBanner] = useState<{ tone: "warning" | "danger" | "info"; message: string } | null>(null);
  const [orderBlockError, setOrderBlockError] = useState<string | null>(null);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [createdOrder, setCreatedOrder] = useState<Order | null>(null);

  // Reset dialog state on open
  useEffect(() => {
    if (!open) return;
    setCustomer(null);
    setSearch("");
    setQuantities({});
    setSiteId("");
    setOrderMode("NEW");
    setRepeatBanner(null);
    setOrderBlockError(null);
    setReviewOpen(false);
    setCreatedOrder(null);
    setIdempotencyKey(newKey());
  }, [open]);

  const debouncedSearch = useDebouncedValue(search.trim());
  const customerParams = {
    merchantId,
    search: debouncedSearch || undefined,
    accountStatus: "ALL",
    customerType: "ALL",
    limit: 10,
    offset: 0,
  };

  const customers = useQuery({
    queryKey: queryKeys.customers.list(customerParams),
    queryFn: ({ signal }) => listCustomers(customerParams, signal),
    enabled: open && !customer && !createdOrder,
    placeholderData: keepPreviousData,
  });

  const customerId = customer?.id ?? "";

  // Eligibility check
  const eligibility = useQuery({
    queryKey: queryKeys.customers.eligibility(merchantId, customerId),
    queryFn: ({ signal }) => getCustomerEligibility(merchantId, customerId, signal),
    enabled: Boolean(customerId),
    retry: false,
  });
  const eligible = eligibility.data?.eligible === true;

  // Credit report query for live credit balance & limits
  const creditQuery = useQuery({
    queryKey: ["admin", "credit", "customer", merchantId, customerId],
    queryFn: ({ signal }) => getCreditReport({ merchantId, limit: 100, offset: 0 }, signal),
    enabled: Boolean(customerId),
    staleTime: 60_000,
  });

  const customerCredit: CustomerCredit | undefined = useMemo(() => {
    if (!customerId || !creditQuery.data?.items) return undefined;
    return creditQuery.data.items.find((c) => c.customerId === customerId);
  }, [customerId, creditQuery.data]);

  // Cylinder types allowed for this customer
  const typesQuery = useQuery({
    queryKey: ["admin", "orders", "cylinder-types", merchantId, customerId],
    queryFn: ({ signal }) => listOrderCylinderTypes(merchantId, customerId, signal),
    enabled: Boolean(customerId) && eligible,
  });

  const availableCylinders = useMemo(() => {
    const list = typesQuery.data ?? [];
    if (list.length > 0) return list;
    if (!customer) return [];
    return cylinderTypesFor(customer.customerType).map((c) => ({
      code: c.code,
      label: c.label,
      minimumQuantity: c.minQuantity,
      maximumQuantity: c.maxQuantity,
    }));
  }, [typesQuery.data, customer]);

  const isIndustrial = customer?.customerType === "INDUSTRIAL";
  const sites = customer?.sites ?? [];

  // Reset or initialize sites when customer changes
  useEffect(() => {
    if (!customer) return;
    if (isIndustrial) {
      const primarySite = sites.find((s) => s.isPrimary) ?? sites[0];
      setSiteId(primarySite?.id ?? "");
    } else {
      setSiteId("");
    }
    setOrderMode("NEW");
    setRepeatBanner(null);
    setOrderBlockError(null);
    setQuantities({});
  }, [customer, isIndustrial]);

  const lines: OrderLine[] = useMemo(
    () =>
      Object.entries(quantities)
        .filter(([, q]) => q > 0)
        .map(([cylinderType, quantity]) => ({ cylinderType, quantity })),
    [quantities]
  );

  const lineErrors = useMemo(() => {
    const errors: Record<string, string> = {};
    for (const type of availableCylinders) {
      const q = quantities[type.code] ?? 0;
      if (q > 0 && q < type.minimumQuantity) {
        errors[type.code] = `At least ${type.minimumQuantity} required`;
      }
      if (q > type.maximumQuantity) {
        errors[type.code] = `Maximum ${type.maximumQuantity} allowed`;
      }
    }
    return errors;
  }, [quantities, availableCylinders]);

  const basketValid = lines.length > 0 && Object.keys(lineErrors).length === 0;
  const basketCount = useMemo(() => lines.reduce((sum, l) => sum + l.quantity, 0), [lines]);

  const debouncedLines = useDebouncedValue(lines, 300);
  const quote = useQuery({
    queryKey: ["admin", "orders", "quote", merchantId, customerId, debouncedLines],
    queryFn: ({ signal }) => quoteOrder(merchantId, customerId, debouncedLines, signal),
    enabled: Boolean(customerId) && eligible && debouncedLines.length > 0 && Object.keys(lineErrors).length === 0,
    placeholderData: keepPreviousData,
    retry: false,
  });

  // Repeat order preview mutation
  const repeatMutation = useMutation({
    mutationFn: () => getRepeatPreview(merchantId, customerId),
    onSuccess: (preview: RepeatPreview) => {
      if (!preview.canReorder) {
        setRepeatBanner({
          tone: "danger",
          message: preview.blockedReason ?? "This customer's last order cannot be repeated.",
        });
        return;
      }
      const newQty: Record<string, number> = {};
      (preview.items ?? []).forEach((item) => {
        newQty[item.cylinderType] = item.quantity;
      });
      setQuantities(newQty);
      if (preview.deliverySiteId) setSiteId(preview.deliverySiteId);

      const notes: string[] = [];
      if (preview.priceChanged) {
        notes.push(`Today's price differs from last order (${formatCurrency(preview.previousTotalAmount)} previously).`);
      }
      if (preview.unavailable?.length) {
        notes.push(
          `Unavailable items: ${preview.unavailable.map((u) => `${u.quantity} × ${u.cylinderLabel} (${u.reason})`).join("; ")}`
        );
      }
      if (notes.length) {
        setRepeatBanner({ tone: "warning", message: notes.join(" ") });
      } else {
        setRepeatBanner({
          tone: "info",
          message: `Loaded previous order ${preview.sourceOrderNumber} from ${formatDate(preview.sourcePlacedAt)}.`,
        });
      }
    },
    onError: (err) => {
      setRepeatBanner({ tone: "danger", message: normalizeError(err).userMessage });
    },
  });

  const handleOrderModeChange = (newMode: "NEW" | "REPEAT") => {
    setOrderMode(newMode);
    setRepeatBanner(null);
    setOrderBlockError(null);
    if (newMode === "REPEAT" && customer) {
      repeatMutation.mutate();
    }
  };

  const placeMutation = useMutation({
    mutationFn: () =>
      createOrder(
        merchantId,
        {
          customerId,
          items: lines,
          orderMode,
          deliverySiteId: isIndustrial ? siteId || null : siteId || undefined,
        },
        idempotencyKey
      ),
    onSuccess: (order) => {
      setReviewOpen(false);
      setCreatedOrder(order);
      setOrderBlockError(null);
      onCreated(order);
    },
    onError: (err: any) => {
      const isCreditBlocked = err?.code === "ORDER_NOT_ALLOWED" || err?.status === 409;
      const msg = normalizeError(err).userMessage;
      setOrderBlockError(msg);
      if (isCreditBlocked) {
        setReviewOpen(false);
      }
    },
  });

  function setQty(code: string, value: number) {
    setQuantities((prev) => ({
      ...prev,
      [code]: Math.max(0, Math.floor(Number.isFinite(value) ? value : 0)),
    }));
    setIdempotencyKey(newKey());
  }

  // Credit calculation
  const creditLimit = customerCredit?.creditLimit ?? 0;
  const runningBalance = customer?.runningBalance ?? 0;
  const availableCredit = customerCredit?.availableCredit ?? Math.max(0, creditLimit - runningBalance);
  const hasCreditConfig = (customerCredit?.creditEnabled && creditLimit > 0) || creditLimit > 0;
  const isCreditExceeded = hasCreditConfig && (availableCredit <= 0 || runningBalance >= creditLimit);

  const canReview =
    Boolean(customer) &&
    eligible &&
    basketValid &&
    (!isIndustrial || Boolean(siteId)) &&
    Boolean(quote.data) &&
    !quote.isFetching;

  // Selected site for Industrial
  const selectedSite = sites.find((s) => s.id === siteId);

  // ---------------------------------------------------------------------------
  // Success State View (matching CreateOrderScreen successHero)
  // ---------------------------------------------------------------------------
  if (createdOrder) {
    return (
      <Modal
        open={open}
        title="Order Placed"
        onClose={onClose}
        footer={
          <div className="row" style={{ gap: 8, justifyContent: "flex-end", width: "100%" }}>
            <Button
              variant="secondary"
              onClick={() => {
                setCreatedOrder(null);
                setCustomer(null);
                setQuantities({});
                setOrderMode("NEW");
                setRepeatBanner(null);
                setOrderBlockError(null);
              }}
            >
              Create Another
            </Button>
            <Button
              variant="primary"
              icon="eye"
              onClick={() => {
                onClose();
              }}
            >
              View Orders
            </Button>
          </div>
        }
      >
        <div className="stack-lg" style={{ textAlign: "center", padding: "16px 8px" }}>
          <div
            style={{
              width: 64,
              height: 64,
              borderRadius: "50%",
              background: "var(--green-50, #f0fdf4)",
              color: "var(--green-600, #16a34a)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              margin: "0 auto",
            }}
          >
            <Icon name="checkCircle" size={36} />
          </div>

          <div>
            <h3 style={{ margin: "0 0 6px" }}>Order Created for {createdOrder.customerName}</h3>
            <div
              style={{
                fontSize: "1.75rem",
                fontWeight: 700,
                color: "var(--blue-600, #2563eb)",
                letterSpacing: "0.5px",
                marginBottom: 8,
              }}
            >
              {createdOrder.orderNumber}
            </div>
            <Badge tone="info">{createdOrder.status}</Badge>
          </div>

          <div
            className="stack"
            style={{
              textAlign: "left",
              background: "var(--surface-muted, #f8fafc)",
              padding: 16,
              borderRadius: 8,
              gap: 12,
            }}
          >
            <div className="table-wrap">
              <table className="data-table" style={{ margin: 0 }}>
                <thead>
                  <tr>
                    <th>Item</th>
                    <th style={{ textAlign: "right" }}>Qty</th>
                    <th style={{ textAlign: "right" }}>Price</th>
                    <th style={{ textAlign: "right" }}>Total</th>
                  </tr>
                </thead>
                <tbody>
                  {(createdOrder.items ?? []).map((it) => (
                    <tr key={it.cylinderType}>
                      <td><strong>{it.cylinderLabel}</strong></td>
                      <td style={{ textAlign: "right" }}>{it.quantity}</td>
                      <td style={{ textAlign: "right" }}>{formatCurrency(it.unitPrice)}</td>
                      <td style={{ textAlign: "right" }}>{formatCurrency(it.lineTotal)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <DetailsPanel
              items={[
                { label: "Customer", value: `${createdOrder.customerName} (${humanize(createdOrder.customerType)})` },
                { label: "Delivery Site", value: createdOrder.deliverySiteName || formatAddress(createdOrder.deliveryAddress) },
                { label: "Order Mode", value: createdOrder.orderMode === "REPEAT" ? "Repeat Order" : "New Order" },
                {
                  label: "Scheduled Delivery",
                  value: `${formatDate(createdOrder.cutoff?.scheduledDeliveryDate || createdOrder.placedAt)} · Cut-off: ${createdOrder.cutoff?.cutoffTime || "18:00"}`,
                },
                {
                  label: "Invoice Estimate",
                  value: <strong style={{ fontSize: "1.1rem" }}>{formatCurrency(createdOrder.totalAmount)}</strong>,
                },
              ]}
            />
          </div>
        </div>
      </Modal>
    );
  }

  // ---------------------------------------------------------------------------
  // Main Create Order Dialog View
  // ---------------------------------------------------------------------------
  return (
    <>
      <Modal
        open={open && !reviewOpen}
        wide
        title="Create Order"
        description="Place an order on behalf of an approved customer, matching the merchant app flow."
        onClose={onClose}
        busy={placeMutation.isPending}
        footer={
          <>
            <Button variant="secondary" onClick={onClose} disabled={placeMutation.isPending}>
              Cancel
            </Button>
            <Button
              variant="primary"
              icon="arrowRight"
              onClick={() => setReviewOpen(true)}
              disabled={!canReview}
              loading={placeMutation.isPending}
            >
              {quote.data && basketValid ? `Review Order (${formatCurrency(quote.data.totalAmount)})` : "Review Order"}
            </Button>
          </>
        }
      >
        <div className="stack" style={{ gap: 14 }}>
          {/* STEP 1: CUSTOMER SELECTION */}
          {!customer ? (
            <Field label="Customer" required hint="Select an approved customer to begin the order.">
              <div className="stack" style={{ gap: 8 }}>
                <SearchInput
                  label="Search customers"
                  placeholder="Search by business name, owner, mobile or code"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  autoFocus
                />
                {customers.isLoading ? (
                  <LoadingSkeleton rows={3} label="Searching customers" />
                ) : customers.error ? (
                  <InlineError error={customers.error} onRetry={() => void customers.refetch()} />
                ) : !customers.data?.items.length ? (
                  <p className="text-muted text-small">No customers match.</p>
                ) : (
                  <ul
                    className="list-plain"
                    style={{
                      border: "1px solid var(--border)",
                      borderRadius: 8,
                      maxHeight: 260,
                      overflowY: "auto",
                    }}
                  >
                    {customers.data.items.map((c) => {
                      const isApproved = c.accountStatus === "APPROVED";
                      return (
                        <li key={c.id} style={{ borderBottom: "1px solid var(--border)" }}>
                          <button
                            type="button"
                            onClick={() => setCustomer(c)}
                            style={{
                              width: "100%",
                              gap: 12,
                              padding: "10px 14px",
                              background: "none",
                              border: 0,
                              textAlign: "left",
                              cursor: "pointer",
                              display: "flex",
                              alignItems: "center",
                              opacity: isApproved ? 1 : 0.7,
                            }}
                          >
                            <UserAvatar name={nameOf(c)} />
                            <span className="cell-stack" style={{ flex: 1, minWidth: 0 }}>
                              <strong style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {nameOf(c)}
                              </strong>
                              <small className="text-muted">
                                {c.mobile} · {humanize(c.customerType)} {c.code ? `· ${c.code}` : ""} · Balance {formatCurrency(c.runningBalance)}
                              </small>
                            </span>
                            <StatusBadge status={c.accountStatus} />
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </Field>
          ) : (
            <div
              className="stack"
              style={{
                padding: "10px 14px",
                border: "1px solid var(--border)",
                borderRadius: 8,
                background: "var(--surface)",
                gap: 6,
              }}
            >
              <div className="row-between" style={{ alignItems: "flex-start", gap: 12 }}>
                <span className="row" style={{ gap: 12, alignItems: "center" }}>
                  <UserAvatar name={nameOf(customer)} />
                  <span className="cell-stack">
                    <strong style={{ fontSize: "1.02rem" }}>{nameOf(customer)}</strong>
                    <small className="text-muted">
                      {humanize(customer.customerType)} · {customer.mobile} · Code: {customer.code || "—"} · Balance {formatCurrency(customer.runningBalance)}
                    </small>
                  </span>
                </span>
                <div className="row" style={{ gap: 8, alignItems: "center" }}>
                  <StatusBadge status={customer.accountStatus} />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setCustomer(null);
                      setQuantities({});
                      setOrderMode("NEW");
                      setRepeatBanner(null);
                    }}
                  >
                    Change
                  </Button>
                </div>
              </div>

              {/* Credit Status Indicator */}
              {hasCreditConfig ? (
                <div
                  className="row"
                  style={{
                    gap: 8,
                    alignItems: "center",
                    padding: "6px 10px",
                    borderRadius: 6,
                    background: isCreditExceeded ? "var(--danger-50, #fef2f2)" : "var(--blue-50, #eff6ff)",
                    color: isCreditExceeded ? "var(--danger-700, #b91c1c)" : "var(--blue-700, #1d4ed8)",
                    border: `1px solid ${isCreditExceeded ? "var(--danger-200, #fecaca)" : "var(--blue-200, #bfdbfe)"}`,
                    fontSize: "0.85rem",
                  }}
                >
                  <Icon name="wallet" size={15} />
                  <span>
                    <strong>Credit:</strong> {formatCurrency(availableCredit)} available / {formatCurrency(creditLimit)} limit
                  </span>
                </div>
              ) : null}
            </div>
          )}

          {/* STEP 2: ELIGIBILITY & CREDIT ALERTS */}
          {customer ? (
            eligibility.isLoading ? (
              <LoadingSkeleton rows={1} label="Checking eligibility" />
            ) : eligibility.error ? (
              <InlineError error={eligibility.error} onRetry={() => void eligibility.refetch()} />
            ) : eligible ? (
              <Alert tone="info" title="Eligible to order">
                Account approved and KYC verified.
              </Alert>
            ) : (
              <Alert tone="warning" title="Customer not eligible">
                {eligibility.data?.reasons?.length ? (
                  <ul style={{ margin: 0, paddingLeft: "1.2em" }}>
                    {eligibility.data.reasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                ) : (
                  "Only approved and verified customers can place orders."
                )}
              </Alert>
            )
          ) : null}

          {/* Credit Limit Alert Banner */}
          {customer && isCreditExceeded ? (
            <Alert tone="error" title="Credit Limit Reached">
              Outstanding balance exceeds the customer's credit limit of {formatCurrency(creditLimit)}. Clear balance to proceed.
            </Alert>
          ) : null}

          {orderBlockError ? (
            <Alert tone="error" title="Order Blocked by Credit Policy">
              {orderBlockError}
            </Alert>
          ) : null}

          {/* STEP 3: ORDER MODE & BASKET */}
          {customer && eligible ? (
            <>
              {/* Mode Switcher: New vs Repeat */}
              <div className="row-between" style={{ alignItems: "center" }}>
                <div className="status-tabs--segmented" role="tablist" aria-label="Order Mode">
                  <button
                    type="button"
                    role="tab"
                    aria-selected={orderMode === "NEW"}
                    onClick={() => handleOrderModeChange("NEW")}
                    style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
                  >
                    <Icon name="plus" size={14} />
                    <span>New Order</span>
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={orderMode === "REPEAT"}
                    onClick={() => handleOrderModeChange("REPEAT")}
                    style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
                  >
                    <Icon name="refresh" size={14} />
                    <span>Repeat Order</span>
                  </button>
                </div>

                {orderMode === "REPEAT" && repeatMutation.isPending ? (
                  <small className="text-muted">Loading last order…</small>
                ) : null}
              </div>

              {repeatBanner ? (
                <Alert tone={repeatBanner.tone === "danger" ? "error" : repeatBanner.tone === "warning" ? "warning" : "info"}>
                  {repeatBanner.message}
                </Alert>
              ) : null}

              {/* Cylinders Picker Table */}
              <div className="stack" style={{ gap: 8 }}>
                <div className="row-between" style={{ alignItems: "center" }}>
                  <strong>Cylinder Types</strong>
                  {basketCount > 0 ? (
                    <small className="text-muted">
                      {basketCount} cylinder{basketCount === 1 ? "" : "s"} in order
                    </small>
                  ) : null}
                </div>
                {typesQuery.isLoading ? (
                  <LoadingSkeleton rows={3} label="Loading cylinders" />
                ) : (
                  <div className="table-wrap">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th style={{ padding: "8px 12px" }}>Cylinder</th>
                          <th style={{ padding: "8px 12px" }}>Limits</th>
                          <th style={{ width: 170, textAlign: "center", padding: "8px 12px" }}>Quantity</th>
                          <th style={{ textAlign: "right", padding: "8px 12px" }}>Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        {availableCylinders.map((type) => {
                          const q = quantities[type.code] ?? 0;
                          const quoted = quote.data?.items?.find((i) => i.cylinderType === type.code);
                          return (
                            <tr key={type.code}>
                              <td style={{ padding: "8px 12px" }}>
                                <div><strong>{type.label}</strong></div>
                                {quoted ? (
                                  <div className="text-muted text-small">{formatCurrency(quoted.unitPrice)} each</div>
                                ) : (
                                  <div className="text-muted text-small">GST incl.</div>
                                )}
                              </td>
                              <td style={{ padding: "8px 12px" }} className="text-muted text-small nowrap">
                                {type.minimumQuantity}–{type.maximumQuantity}
                              </td>
                              <td style={{ padding: "8px 12px", textAlign: "center" }}>
                                <div style={{ display: "inline-flex", justifyContent: "center" }}>
                                  <div className="stepper" role="group" aria-label={`Quantity for ${type.label}`}>
                                    <button
                                      type="button"
                                      className="stepper__btn"
                                      aria-label={`Decrease ${type.label}`}
                                      onClick={() => setQty(type.code, Math.max(0, q - 1))}
                                      disabled={q <= 0}
                                    >
                                      <Icon name="minus" size={14} />
                                    </button>
                                    <input
                                      type="number"
                                      className="stepper__input"
                                      min={0}
                                      max={type.maximumQuantity}
                                      value={q === 0 ? "" : q}
                                      placeholder="0"
                                      onChange={(e) => {
                                        const raw = e.target.value;
                                        setQty(type.code, raw === "" ? 0 : Math.max(0, parseInt(raw, 10) || 0));
                                      }}
                                    />
                                    <button
                                      type="button"
                                      className="stepper__btn"
                                      aria-label={`Increase ${type.label}`}
                                      onClick={() => setQty(type.code, q === 0 ? Math.max(1, type.minimumQuantity) : q + 1)}
                                      disabled={q >= type.maximumQuantity}
                                    >
                                      <Icon name="plus" size={14} />
                                    </button>
                                  </div>
                                </div>
                                {lineErrors[type.code] ? (
                                  <small style={{ color: "var(--red-600, #dc2626)", display: "block", textAlign: "center", marginTop: 4 }}>
                                    {lineErrors[type.code]}
                                  </small>
                                ) : null}
                              </td>
                              <td style={{ padding: "8px 12px", textAlign: "right" }} className="nowrap">
                                {quoted ? formatCurrency(quoted.lineTotal) : q ? "…" : "—"}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* STEP 4: DELIVERY SITE */}
              {isIndustrial ? (
                <Field
                  label="Delivery Site"
                  required
                  error={!siteId ? "Industrial orders require a delivery site." : undefined}
                >
                  <Select
                    value={siteId}
                    onChange={(e) => setSiteId(e.target.value)}
                    placeholder="Choose a delivery site"
                    options={sites.map((s) => ({
                      value: s.id,
                      label: `${s.name}${s.isPrimary ? " (Primary)" : ""} — ${s.address?.line1 || ""}, ${s.address?.city || ""}`,
                    }))}
                  />
                </Field>
              ) : (
                <div
                  className="stack"
                  style={{
                    padding: "10px 14px",
                    borderRadius: 6,
                    background: "var(--surface-muted, #f8fafc)",
                    border: "1px solid var(--border)",
                    gap: 4,
                  }}
                >
                  <small className="text-muted" style={{ textTransform: "uppercase", letterSpacing: "0.5px" }}>
                    Delivery Site
                  </small>
                  <span>Registered address · {formatAddress(customer.deliveryAddress)}</span>
                </div>
              )}

              {/* STEP 5: REAL-TIME PRICE SUMMARY */}
              {quote.error ? (
                <Alert tone="error">{normalizeError(quote.error).userMessage}</Alert>
              ) : quote.data && lines.length > 0 ? (
                <div
                  className="stack"
                  style={{
                    gap: 10,
                    padding: 14,
                    borderRadius: 8,
                    background: "var(--surface-muted, #f8fafc)",
                    border: "1px solid var(--border)",
                  }}
                >
                  <DetailsPanel
                    items={[
                      { label: "Total Cylinders", value: formatNumber(quote.data.totalCylinders) },
                      { label: "Taxable Value (Subtotal)", value: formatCurrency(quote.data.subtotal) },
                      { label: `GST (${quote.data.gstPercent}%)`, value: formatCurrency(quote.data.gstAmount) },
                      {
                        label: "Total (GST Incl.)",
                        value: <strong style={{ fontSize: "1.2rem", color: "var(--blue-700, #1d4ed8)" }}>{formatCurrency(quote.data.totalAmount)}</strong>,
                      },
                    ]}
                  />
                  <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <Badge tone={quote.data.cutoff.withinCutoff ? "success" : "warning"}>
                      Delivery: {formatDate(quote.data.cutoff.scheduledDeliveryDate)}
                    </Badge>
                    <small className="text-muted">{quote.data.cutoff.message}</small>
                    {orderMode === "REPEAT" ? <Badge tone="info">Repeat Order</Badge> : null}
                  </div>
                </div>
              ) : null}
            </>
          ) : null}
        </div>
      </Modal>

      {/* STEP 6: TWO-STEP REVIEW & CONFIRM MODAL */}
      <Modal
        open={reviewOpen}
        title="Review & Confirm Order"
        description={customer ? `Please verify order details before placing for ${customer.businessName || customer.ownerName}.` : ""}
        onClose={() => setReviewOpen(false)}
        busy={placeMutation.isPending}
        footer={
          <>
            <Button variant="secondary" onClick={() => setReviewOpen(false)} disabled={placeMutation.isPending}>
              Back to Edit
            </Button>
            <Button
              variant="primary"
              icon="check"
              onClick={() => placeMutation.mutate()}
              loading={placeMutation.isPending}
              loadingText="Creating Order…"
            >
              Create Order
            </Button>
          </>
        }
      >
        {customer && quote.data ? (
          <div className="stack-lg">
            <div
              className="stack"
              style={{
                padding: "12px 14px",
                borderRadius: 8,
                background: "var(--surface-muted, #f8fafc)",
                border: "1px solid var(--border)",
                gap: 10,
              }}
            >
              <DetailsPanel
                items={[
                  { label: "Customer", value: nameOf(customer) },
                  { label: "Customer Type", value: humanize(customer.customerType) },
                  {
                    label: "Delivery Site",
                    value: isIndustrial
                      ? selectedSite?.name || "Selected site"
                      : "Registered Address",
                  },
                  { label: "Order Mode", value: orderMode === "REPEAT" ? "Repeat Order" : "New Order" },
                  {
                    label: "Scheduled Delivery",
                    value: formatDate(quote.data.cutoff.scheduledDeliveryDate),
                  },
                ]}
              />

              <div style={{ marginTop: 8 }}>
                <strong>Order Items Breakdown</strong>
                <div className="table-wrap" style={{ marginTop: 6 }}>
                  <table className="data-table" style={{ margin: 0 }}>
                    <thead>
                      <tr>
                        <th>Cylinder</th>
                        <th style={{ textAlign: "right" }}>Qty</th>
                        <th style={{ textAlign: "right" }}>Unit Price</th>
                        <th style={{ textAlign: "right" }}>Total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(quote.data.items ?? []).map((it) => (
                        <tr key={it.cylinderType}>
                          <td><strong>{it.cylinderLabel}</strong></td>
                          <td style={{ textAlign: "right" }}>{it.quantity}</td>
                          <td style={{ textAlign: "right" }}>{formatCurrency(it.unitPrice)}</td>
                          <td style={{ textAlign: "right" }}>{formatCurrency(it.lineTotal)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div
                className="row-between"
                style={{
                  paddingTop: 8,
                  borderTop: "1px solid var(--border)",
                  fontSize: "1.1rem",
                }}
              >
                <span>Estimated Total:</span>
                <strong style={{ color: "var(--blue-700, #1d4ed8)" }}>
                  {formatCurrency(quote.data.totalAmount)}
                </strong>
              </div>
            </div>

            {placeMutation.error ? (
              <Alert tone="error" title={normalizeError(placeMutation.error).userMessage}>
                {(placeMutation.error as any)?.code === "ORDER_NOT_ALLOWED" ||
                (placeMutation.error as any)?.status === 409
                  ? "This order was blocked because the customer's credit limit has been exceeded."
                  : undefined}
              </Alert>
            ) : null}
          </div>
        ) : null}
      </Modal>
    </>
  );
}
export default CreateOrderDialog;
