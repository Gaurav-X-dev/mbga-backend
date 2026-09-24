import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  changeDeliveryMemberStatus,
  type DeliveryMember,
  type DeliveryMemberStatusAction
} from "../../api/delivery-team.api";
import { queryKeys } from "../../api/query-keys";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import type { MenuAction } from "../../components/common/Menu";
import { ConfirmationDialog } from "../../components/feedback/Dialogs";
import { useToast } from "../../components/feedback/toast-context";

type Pending = { member: DeliveryMember; action: DeliveryMemberStatusAction } | null;

export function useDeliveryMemberStatus() {
  const auth = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<Pending>(null);

  const mutation = useMutation({
    mutationFn: ({ member, action }: NonNullable<Pending>) => changeDeliveryMemberStatus(member.id, action),
    onSuccess: (updated, { action }) => {
      queryClient.setQueryData(queryKeys.deliveryTeam.detail(updated.id), updated);
      void queryClient.invalidateQueries({ queryKey: queryKeys.deliveryTeam.lists() });
      const name = updated.full_name ?? "The team member";
      toast.success(action === "block" ? `${name} has been blocked.` : `${name} can use the Delivery app again.`);
    }
  });

  function actionsFor(member: DeliveryMember): MenuAction[] {
    const blocked = member.status === "BLOCKED";
    return [
      {
        label: "Block team member",
        icon: "ban",
        danger: true,
        hidden: blocked || !auth.can(PERMISSIONS.deliveryUsersBlock),
        onSelect: () => setPending({ member, action: "block" })
      },
      {
        label: blocked ? "Unblock team member" : "Activate team member",
        icon: "unlock",
        hidden: member.status === "ACTIVE" || !auth.can(PERMISSIONS.deliveryUsersActivate),
        onSelect: () => setPending({ member, action: blocked ? "unblock" : "activate" })
      }
    ];
  }

  const isBlock = pending?.action === "block";
  const name = pending?.member.full_name ?? "this team member";
  const dialog = (
    <ConfirmationDialog
      open={pending !== null}
      title={isBlock ? `Block ${name}?` : `Reactivate ${name}?`}
      description={
        isBlock
          ? "They will be signed out of the Delivery app immediately and will not be able to sign in until unblocked."
          : "They will be able to sign in to the Delivery app again."
      }
      confirmLabel={isBlock ? "Block team member" : "Reactivate"}
      confirmVariant={isBlock ? "danger" : "primary"}
      onClose={() => setPending(null)}
      onConfirm={() => (pending ? mutation.mutateAsync(pending) : undefined)}
    />
  );

  return { actionsFor, dialog };
}
