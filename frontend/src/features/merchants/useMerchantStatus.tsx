import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { changeMerchantStatus, type Merchant, type MerchantStatusAction } from "../../api/merchants.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import type { MenuAction } from "../../components/common/Menu";
import { ConfirmationDialog } from "../../components/feedback/Dialogs";
import { useToast } from "../../components/feedback/toast-context";

type Pending = { merchant: Merchant; action: MerchantStatusAction } | null;

/** Block / unblock actions with confirmation, shared by the list and detail pages. */
export function useMerchantStatusActions() {
  const auth = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<Pending>(null);

  const mutation = useMutation({
    mutationFn: ({ merchant, action }: NonNullable<Pending>) => changeMerchantStatus(merchant.id, action),
    onSuccess: (updated, { action }) => {
      queryClient.setQueryData<Merchant>(queryKeys.merchants.detail(updated.id), (previous) =>
        previous ? { ...previous, status: updated.status, approval_status: updated.approval_status } : updated
      );
      void queryClient.invalidateQueries({ queryKey: queryKeys.merchants.lists() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.adminDashboard.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      toast.success(
        action === "block"
          ? `${updated.business_name} has been blocked.`
          : `${updated.business_name} is active again.`
      );
    }
  });

  function actionsFor(merchant: Merchant): MenuAction[] {
    const blocked = merchant.status === "BLOCKED";
    return [
      {
        label: "Block account",
        icon: "ban",
        danger: true,
        hidden: blocked || !auth.can(PERMISSIONS.merchantsBlock),
        onSelect: () => setPending({ merchant, action: "block" })
      },
      {
        label: blocked ? "Unblock account" : "Activate account",
        icon: "unlock",
        hidden: merchant.status === "ACTIVE" || !auth.can(PERMISSIONS.merchantsActivate),
        onSelect: () => setPending({ merchant, action: blocked ? "unblock" : "activate" })
      }
    ];
  }

  const isBlock = pending?.action === "block";
  const dialog = (
    <ConfirmationDialog
      open={pending !== null}
      title={isBlock ? `Block ${pending?.merchant.business_name}?` : `Reactivate ${pending?.merchant.business_name}?`}
      description={
        isBlock
          ? "The merchant and all of their staff will be signed out immediately and will not be able to sign in until the account is unblocked."
          : "The merchant’s staff will be able to sign in to the Merchant panel again."
      }
      confirmLabel={isBlock ? "Block account" : "Reactivate account"}
      confirmVariant={isBlock ? "danger" : "primary"}
      onClose={() => setPending(null)}
      onConfirm={() => (pending ? mutation.mutateAsync(pending) : undefined)}
    />
  );

  return { actionsFor, dialog };
}
