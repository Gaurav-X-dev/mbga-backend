import type { PropsWithChildren } from "react";
import { Navigate } from "react-router-dom";

import { useAuth } from "./AuthProvider";

export function ProtectedRoute({ children }: PropsWithChildren) {
  const auth = useAuth();
  if (!auth.isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return children;
}
