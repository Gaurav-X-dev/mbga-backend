import { createContext, useContext, useMemo, useState } from "react";
import type { PropsWithChildren } from "react";

import { fetchMe, logout, type AuthChannel, type MeResponse, type TokenPair } from "../api/auth.api";

type AuthState = {
  channel: AuthChannel | null;
  accessToken: string | null;
  refreshToken: string | null;
  user: MeResponse | null;
  isAuthenticated: boolean;
  completeLogin: (channel: AuthChannel, token: TokenPair) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [channel, setChannel] = useState<AuthChannel | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState<string | null>(null);
  const [user, setUser] = useState<MeResponse | null>(null);

  const value = useMemo<AuthState>(
    () => ({
      channel,
      accessToken,
      refreshToken,
      user,
      isAuthenticated: Boolean(accessToken && user),
      async completeLogin(nextChannel, token) {
        const me = await fetchMe(nextChannel, token.access_token);
        setChannel(nextChannel);
        setAccessToken(token.access_token);
        setRefreshToken(token.refresh_token);
        setUser(me);
      },
      async signOut() {
        if (channel) {
          await logout(channel, refreshToken);
        }
        setChannel(null);
        setAccessToken(null);
        setRefreshToken(null);
        setUser(null);
      }
    }),
    [accessToken, channel, refreshToken, user]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
