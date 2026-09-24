import type { PropsWithChildren } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { FullPageLoader } from "../components/feedback/Feedback";
import { AccessDeniedPage, ServiceUnavailablePage } from "../features/system/SystemPages";
import { useAuth } from "./auth-context";
import type { AuthChannel } from "./token-storage";

type ProtectedRouteProps = PropsWithChildren<{
  /** The panel this route tree belongs to. A session for another panel is refused. */
  channel: AuthChannel;
}>;

/**
 * Authentication + channel guard. The backend remains authoritative: this only avoids
 * rendering screens the current session could never use.
 */
export function ProtectedRoute({ channel, children }: ProtectedRouteProps) {
  const auth = useAuth();
  const location = useLocation();

  if (auth.status === "anonymous") {
    const from = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to="/login" replace state={{ from }} />;
  }
  if (auth.status === "loading") {
    return <FullPageLoader />;
  }
  if (auth.status === "unavailable") {
    return <ServiceUnavailablePage onRetry={auth.retryBootstrap} message={auth.bootstrapError?.userMessage} />;
  }
  if (auth.channel !== channel) {
    return <AccessDeniedPage />;
  }
  return children;
}
