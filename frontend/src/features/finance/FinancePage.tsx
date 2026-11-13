import { useQuery } from "@tanstack/react-query";
import { listMerchants } from "../../api/merchants.api";
import { useAuth } from "../../auth/auth-context";
import { Navigate, useLocation } from "react-router-dom";
import { Field, Select } from "../../components/forms/Field";
import { Card, PageHeader } from "../../components/layout/Page";
import { EmptyState, ErrorState } from "../../components/feedback/Feedback";
import { useUrlFilters } from "../../hooks/useUrlFilters";
import { Advances } from "./Advances";
import { CashHandovers } from "./CashHandovers";
import "./finance.css";

const FILTERS = ["merchant", "view"] as const;
export function FinancePage({ view: pageView }: { view?: "advance" | "cash" }) {
  const location = useLocation();
  const auth = useAuth(); const merchant = auth.channel === "merchant";
  const { values, setFilter } = useUrlFilters(FILTERS);
  const merchantId = merchant ? String(auth.user?.merchant?.id || "") : values.merchant;
  const merchants = useQuery({ queryKey: ["finance-merchants"], queryFn: ({ signal }) => listMerchants({ limit: 100, offset: 0 }, signal), enabled: !merchant && auth.can("merchants.view") });
  const view = pageView || (values.view === "cash" ? "cash" : "advance");
  if (!pageView) return <Navigate replace to={`${merchant ? "/merchant" : "/admin"}/finance/${view === "cash" ? "cash-handovers" : "advances"}${location.search}`} />;
  if (!auth.can("payments.view")) return <Card><EmptyState title="You do not have access to finance records" /></Card>;
  return <div className="page stack finance-page">
    <PageHeader title={view === "advance" ? "Customer advance collections" : "Driver cash collections"} description={view === "advance" ? "Record and verify customer advances, review balances and refunds." : "Reconcile driver cash with invoices and verify office handovers."} actions={!merchant ? <Field label="Merchant" hideLabel><Select value={merchantId} placeholder="Select a merchant" options={(merchants.data?.items || []).map(m => ({ value: m.id, label: m.business_name }))} onChange={e => setFilter("merchant", e.target.value)} /></Field> : undefined} />

    {merchants.isError ? <ErrorState error={merchants.error} onRetry={() => void merchants.refetch()} /> : null}
    {merchantId ? view === "advance" ? <Advances key={merchantId} scope={{ merchant, merchantId }} /> : <CashHandovers key={merchantId} scope={{ merchant, merchantId }} /> : <Card><EmptyState title="Select a merchant to load finance records" /></Card>}
  </div>;
}
