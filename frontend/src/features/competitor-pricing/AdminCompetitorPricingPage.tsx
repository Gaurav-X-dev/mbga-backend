import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { createCompetitorPricingApi } from "../../api/competitor-pricing.api";
import { listMerchants } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { EmptyState, InlineError, LoadingSkeleton } from "../../components/feedback/Feedback";
import { Field, Input, Select } from "../../components/forms/Field";
import { Card, PageHeader } from "../../components/layout/Page";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import { CompetitorPricingPage } from "./CompetitorPricingPage";

/** An explicit merchant selection keeps platform-admin operations tenant scoped. */
export function AdminCompetitorPricingPage() {
  const auth = useAuth();
  const [selected, setSelected] = useState({ id: "", label: "" });
  const [search, setSearch] = useState("");
  const term = useDebouncedValue(search, 300);
  const params = { search: term || undefined, limit: 100, offset: 0 };
  const merchants = useQuery({
    queryKey: [...queryKeys.merchants.list(params), auth.user?.user_id],
    queryFn: ({ signal }) => listMerchants(params, signal)
  });
  const api = useMemo(() => selected.id ? createCompetitorPricingApi(selected.id) : undefined, [selected.id]);
  const options = (merchants.data?.items ?? []).map(merchant => ({ value: merchant.id, label: `${merchant.business_name} (${merchant.merchant_code})` }));
  if (selected.id && !options.some(option => option.value === selected.id)) options.unshift({ value: selected.id, label: selected.label });
  return <div className="stack">
    {!selected.id && <PageHeader title="Competitor pricing" description="Choose a merchant to view and manage its market prices, competitor directory and surveys." />}
    <Card title="Merchant scope" subtitle="Changes are recorded against the selected merchant using your Admin identity.">
      <div className="market-filters">
        <Field label="Find merchant"><Input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search merchant name or code" /></Field>
        <Field label="Select merchant" required><Select placeholder="Choose a merchant" value={selected.id} options={options} onChange={event => { const option = options.find(item => item.value === event.target.value); setSelected({ id: option?.value ?? "", label: option?.label ?? "" }); }} /></Field>
      </div>
      {merchants.isLoading && <LoadingSkeleton />}
      <InlineError error={merchants.error} onRetry={() => void merchants.refetch()} />
      {merchants.data && merchants.data.total > merchants.data.items.length && <p className="text-muted">Showing up to 100 matches. Search to find another merchant.</p>}
      {merchants.data && !merchants.data.items.length && <EmptyState title="No matching merchants" description="Try another merchant name or code." />}
    </Card>
    {api && <CompetitorPricingPage key={selected.id} api={api} channel="admin" merchantId={selected.id} />}
  </div>;
}
