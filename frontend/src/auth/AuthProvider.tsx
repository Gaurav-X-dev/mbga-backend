import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import type { PropsWithChildren } from "react";

import { fetchMe, logout, logoutAll, type MeResponse, type TokenPair } from "../api/auth.api";
import { setSessionExpiredHandler } from "../api/client";
import { AppError, isRetryableError, normalizeError } from "../api/errors";
import { queryKeys } from "../api/query-keys";
import { AuthContext, type AuthContextValue, type AuthStatus, type SessionEndReason } from "./auth-context";
import { hasPermission } from "./permissions";
import { tokenStorage, type AuthChannel } from "./token-storage";

const EMPTY: readonly string[] = [];

function channelMatches(me: MeResponse, channel: AuthChannel): boolean {
  return (me.login_channel ?? "").toUpperCase() === channel.toUpperCase();
}

export function AuthProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const session = useSyncExternalStore(tokenStorage.subscribe, tokenStorage.get, tokenStorage.get);
  const [endReason, setEndReason] = useState<SessionEndReason>(null);
  const channel = session?.channel ?? null;

  useEffect(() => {
    setSessionExpiredHandler(() => {
      setEndReason("expired");
      queryClient.clear();
    });
    return () => setSessionExpiredHandler(null);
  }, [queryClient]);

  const meQuery = useQuery({
    queryKey: queryKeys.me(channel ?? "none"),
    queryFn: async ({ signal }) => {
      const me = await fetchMe(channel as AuthChannel, undefined, signal);
      if (!channelMatches(me, channel as AuthChannel)) {
        throw new AppError({ kind: "forbidden", userMessage: "Your account does not have access to this panel." });
      }
      return me;
    },
    enabled: channel !== null,
    staleTime: 5 * 60_000,
    gcTime: Infinity,
    refetchOnWindowFocus: false,
    retry: (failureCount, error) => failureCount < 2 && isRetryableError(error)
  });

  const bootstrapError = useMemo(() => (meQuery.error ? normalizeError(meQuery.error) : null), [meQuery.error]);

  // A session the backend no longer accepts for this panel is discarded.
  useEffect(() => {
    if (bootstrapError && (bootstrapError.kind === "unauthorized" || bootstrapError.kind === "forbidden")) {
      if (tokenStorage.get()) {
        tokenStorage.clear();
        setEndReason("expired");
        queryClient.clear();
      }
    }
  }, [bootstrapError, queryClient]);

  let status: AuthStatus;
  if (!session) status = "anonymous";
  else if (meQuery.data) status = "authenticated";
  else if (
    bootstrapError &&
    !meQuery.isFetching &&
    bootstrapError.kind !== "unauthorized" &&
    bootstrapError.kind !== "forbidden"
  )
    status = "unavailable";
  else status = "loading";

  const user = session ? meQuery.data ?? null : null;
  const permissions = user?.effective_permissions ?? EMPTY;
  const { refetch } = meQuery;

  const completeLogin = useCallback(
    async (nextChannel: AuthChannel, token: TokenPair) => {
      const me = await fetchMe(nextChannel, token.access_token);
      if (!channelMatches(me, nextChannel)) {
        // Best effort: do not leave an unusable session behind.
        await logout(nextChannel, token.refresh_token).catch(() => undefined);
        throw new AppError({
          kind: "forbidden",
          userMessage: "Your account does not have access to this panel."
        });
      }
      queryClient.clear();
      queryClient.setQueryData(queryKeys.me(nextChannel), me);
      tokenStorage.set({
        channel: nextChannel,
        accessToken: token.access_token,
        refreshToken: token.refresh_token
      });
      setEndReason(null);
      return me;
    },
    [queryClient]
  );

  const endLocalSession = useCallback(() => {
    tokenStorage.clear();
    queryClient.clear();
    setEndReason("signed_out");
  }, [queryClient]);

  const signOut = useCallback(async () => {
    const current = tokenStorage.get();
    if (current) {
      // Sign-out must always succeed locally, even if the server cannot be reached.
      await logout(current.channel, current.refreshToken).catch(() => undefined);
    }
    endLocalSession();
  }, [endLocalSession]);

  const signOutEverywhere = useCallback(async () => {
    const current = tokenStorage.get();
    if (!current) return;
    await logoutAll(current.channel);
    endLocalSession();
  }, [endLocalSession]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      channel,
      user,
      permissions,
      isAuthenticated: status === "authenticated",
      endReason,
      bootstrapError,
      retryBootstrap: () => void refetch(),
      completeLogin,
      signOut,
      signOutEverywhere,
      can: (permission) => hasPermission(permissions, permission),
      clearEndReason: () => setEndReason(null)
    }),
    [status, channel, user, permissions, endReason, bootstrapError, refetch, completeLogin, signOut, signOutEverywhere]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
