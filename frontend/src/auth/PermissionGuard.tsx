import type { PropsWithChildren } from "react";

import { useAuth } from "./AuthProvider";

type PermissionGuardProps = PropsWithChildren<{
  permission: string;
}>;

export function PermissionGuard({ children, permission }: PermissionGuardProps) {
  const auth = useAuth();
  if (!auth.user?.effective_permissions.includes(permission)) {
    return null;
  }
  return children;
}
