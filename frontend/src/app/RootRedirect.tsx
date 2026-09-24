import { Navigate } from "react-router-dom";

import { useAuth } from "../auth/auth-context";
import { CHANNEL_HOME } from "../auth/permissions";
import { FullPageLoader } from "../components/feedback/Feedback";

/** "/" sends signed-in users to their panel home and everyone else to sign in. */
export function RootRedirect() {
  const auth = useAuth();
  if (auth.status === "loading") return <FullPageLoader />;
  if (auth.channel) return <Navigate to={CHANNEL_HOME[auth.channel]} replace />;
  return <Navigate to="/login" replace />;
}
