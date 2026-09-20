import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { queryKeys } from "../../api/query-keys";
import { changeUserStatus, signOutUserEverywhere, type User, type UserStatusAction } from "../../api/users.api";
import { useAuth } from "../../auth/auth-context";
import { PERMISSIONS } from "../../auth/permissions";
import type { MenuAction } from "../../components/common/Menu";
import { ConfirmationDialog } from "../../components/feedback/Dialogs";
import { useToast } from "../../components/feedback/toast-context";

type PendingAction = UserStatusAction | "sign-out";
type Pending = { user: User; action: PendingAction } | null;

function name(user: User) {
  return user.full_name || user.email || "this user";
}

const COPY: Record<PendingAction, { title: (user: User) => string; description: string; confirm: string; danger: boolean }> = {
  block: {
    title: (user) => `Block ${name(user)}?`,
    description: "They will not be able to sign in, and their current sign-in will stop working within a few minutes. To end their sessions immediately, also sign them out from all devices.",
    confirm: "Block account",
    danger: true
  },
  unblock: {
    title: (user) => `Unblock ${name(user)}?`,
    description: "They will be able to sign in again with their mobile number.",
    confirm: "Unblock account",
    danger: false
  },
  activate: {
    title: (user) => `Activate ${name(user)}?`,
    description: "They will be able to sign in to the panels their roles allow.",
    confirm: "Activate account",
    danger: false
  },
  "sign-out": {
    title: (user) => `Sign ${name(user)} out from all devices?`,
    description: "They will need to sign in again on every device. Their account stays active.",
    confirm: "Sign out from all devices",
    danger: true
  }
};

export function useUserStatusActions() {
  const auth = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<Pending>(null);

  const mutation = useMutation({
    mutationFn: async ({ user, action }: NonNullable<Pending>) => {
      if (action === "sign-out") {
        await signOutUserEverywhere(user.id);
        return user;
      }
      return changeUserStatus(user.id, action);
    },
    onSuccess: (updated, { action }) => {
      if (action !== "sign-out") {
        queryClient.setQueryData(queryKeys.users.detail(updated.id), updated);
        void queryClient.invalidateQueries({ queryKey: queryKeys.users.lists() });
        void queryClient.invalidateQueries({ queryKey: queryKeys.users.channels(updated.id) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.adminDashboard.all });
      } else {
        void queryClient.invalidateQueries({ queryKey: queryKeys.adminDashboard.all });
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.auditLogs.all });
      const messages: Record<PendingAction, string> = {
        block: `${name(updated)} has been blocked.`,
        unblock: `${name(updated)} has been unblocked.`,
        activate: `${name(updated)} is now active.`,
        "sign-out": `${name(updated)} has been signed out from all devices.`
      };
      toast.success(messages[action]);
    }
  });

  function actionsFor(user: User): MenuAction[] {
    const isSelf = auth.user?.user_id === user.id;
    return [
      {
        label: "Activate account",
        icon: "unlock",
        hidden: user.status === "ACTIVE" || user.status === "BLOCKED" || !auth.can(PERMISSIONS.usersActivate),
        onSelect: () => setPending({ user, action: "activate" })
      },
      {
        label: "Unblock account",
        icon: "unlock",
        hidden: user.status !== "BLOCKED" || !auth.can(PERMISSIONS.usersBlock),
        onSelect: () => setPending({ user, action: "unblock" })
      },
      {
        label: "Sign out from all devices",
        icon: "devices",
        hidden: isSelf || !auth.can(PERMISSIONS.usersRevokeSessions),
        onSelect: () => setPending({ user, action: "sign-out" })
      },
      {
        label: "Block account",
        icon: "ban",
        danger: true,
        // You cannot block your own account from here.
        hidden: isSelf || user.status === "BLOCKED" || !auth.can(PERMISSIONS.usersBlock),
        onSelect: () => setPending({ user, action: "block" })
      }
    ];
  }

  const copy = pending ? COPY[pending.action] : null;
  const dialog = (
    <ConfirmationDialog
      open={pending !== null}
      title={pending && copy ? copy.title(pending.user) : ""}
      description={copy?.description ?? ""}
      confirmLabel={copy?.confirm ?? "Confirm"}
      confirmVariant={copy?.danger ? "danger" : "primary"}
      onClose={() => setPending(null)}
      onConfirm={() => (pending ? mutation.mutateAsync(pending) : undefined)}
    />
  );

  return { actionsFor, dialog };
}
