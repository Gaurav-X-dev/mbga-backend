import { createContext, useContext } from "react";

import type { MeResponse, TokenPair } from "../api/auth.api";
import type { AppError } from "../api/errors";
import type { AuthChannel } from "./token-storage";

export type AuthStatus = "anonymous" | "loading" | "authenticated" | "unavailable";
export type SessionEndReason = "expired" | "signed_out" | null;

export type AuthContextValue = {
  status: AuthStatus;
  channel: AuthChannel | null;
  user: MeResponse | null;
  permissions: readonly string[];
  isAuthenticated: boolean;
  /** Why the last session ended; shown once on the sign-in page. */
  endReason: SessionEndReason;
  bootstrapError: AppError | null;
  retryBootstrap: () => void;
  completeLogin: (channel: AuthChannel, token: TokenPair) => Promise<MeResponse>;
  signOut: () => Promise<void>;
  signOutEverywhere: () => Promise<void>;
  can: (permission: string | readonly string[]) => boolean;
  clearEndReason: () => void;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
