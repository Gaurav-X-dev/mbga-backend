import type { PropsWithChildren, ReactNode } from "react";

import { AccessDeniedContent } from "../features/system/SystemPages";
import { useAuth } from "./auth-context";

type PermissionGuardProps = PropsWithChildren<{
  /** All listed permissions are required. */
  permission: string | readonly string[];
  /** Rendered when the permission is missing. Defaults to nothing (hide the control). */
  fallback?: ReactNode;
}>;

/** Hides UI the current account cannot use. The backend still enforces every permission. */
export function PermissionGuard({ children, permission, fallback = null }: PermissionGuardProps) {
  const auth = useAuth();
  return auth.can(permission) ? children : fallback;
}

/** Route-level variant: shows the access-denied content inside the app shell. */
export function RequirePermission({ children, permission }: PropsWithChildren<{ permission: string | readonly string[] }>) {
  return (
    <PermissionGuard permission={permission} fallback={<AccessDeniedContent />}>
      {children}
    </PermissionGuard>
  );
}
