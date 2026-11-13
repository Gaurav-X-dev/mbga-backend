import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { queryKeys } from "../../api/query-keys";
import { listMerchants } from "../../api/merchants.api";
import { grantMerchantAccess, listMerchantAccess } from "../../api/users.api";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import { Button } from "../../components/common/Button";
import { ErrorState } from "../../components/feedback/Feedback";
import { useToast } from "../../components/feedback/toast-context";
import { Field, Select } from "../../components/forms/Field";
import { Card } from "../../components/layout/Page";

export function MerchantAccessCard({ userId }: { userId: string }) {
  const auth = useAuth();
  const client = useQueryClient();
  const toast = useToast();
  const [merchantId, setMerchantId] = useState("");
  const canGrant = auth.can(PERMISSIONS.merchantUsersCreate) && auth.can(PERMISSIONS.merchantsView);
  const access = useQuery({ queryKey: ["user-merchant-access", userId], queryFn: ({ signal }) => listMerchantAccess(userId, signal) });
  const merchants = useQuery({
    queryKey: ["merchant-access-options"],
    queryFn: async ({ signal }) => {
      const items = [];
      let offset = 0;
      while (true) {
        const page = await listMerchants({ limit: 100, offset }, signal);
        items.push(...page.items);
        offset += page.items.length;
        if (!page.items.length || offset >= page.total) return items;
      }
    },
    enabled: canGrant
  });
  const mutation = useMutation({
    mutationFn: () => grantMerchantAccess(userId, merchantId),
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["user-merchant-access", userId] });
      void client.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      toast.success("Merchant access assigned. The user can sign in with their existing role.");
    }
  });
  const linked = access.data?.some((item) => item.status === "ACTIVE");
  return <Card title="Merchant app access">
    <div className="stack">
      <p className="meta">Link this user to their merchant. Their assigned role controls app permissions.</p>
      {access.error ? <ErrorState error={access.error} onRetry={() => void access.refetch()} /> : null}
      {access.data?.map((item) => <p key={item.merchant_id}>{item.merchant_name} · {item.status}</p>)}
      {canGrant && !linked ? <>
        {merchants.error ? <ErrorState error={merchants.error} onRetry={() => void merchants.refetch()} /> : null}
        <Field label="Merchant" required>
          <Select value={merchantId} onChange={(event) => setMerchantId(event.target.value)}
            options={(merchants.data ?? []).filter((item) => item.status === "ACTIVE" && item.approval_status === "APPROVED").map((item) => ({ value: item.id, label: item.business_name }))}
            placeholder="Choose a merchant" disabled={merchants.isLoading || access.isLoading || mutation.isPending} />
        </Field>
        {mutation.error ? <ErrorState error={mutation.error} /> : null}
        <Button variant="primary" disabled={!merchantId || access.isLoading || !!access.error} loading={mutation.isPending} onClick={() => mutation.mutate()}>Assign merchant access</Button>
      </> : null}
    </div>
  </Card>;
}
