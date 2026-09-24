import axios, { type InternalAxiosRequestConfig } from "axios";

import { tokenStorage, type StoredSession } from "../auth/token-storage";
import { env } from "../config/env";
import { AppError, MESSAGES, normalizeError } from "./errors";

declare module "axios" {
  interface AxiosRequestConfig {
    /** Do not attach the stored access token (public endpoints, or an explicit token is supplied). */
    skipAuth?: boolean;
    /** Do not try to refresh the session when this request returns 401. */
    skipAuthRefresh?: boolean;
    /** Internal: request has already been retried after a refresh. */
    _retried?: boolean;
  }
}

export const WEB_DEVICE = { device_type: "web", device_id: "mbga-web-panel" } as const;

export const apiClient = axios.create({
  baseURL: env.apiBaseUrl,
  timeout: 15_000,
  headers: { Accept: "application/json" }
});

type TokenPairResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
};

let refreshPromise: Promise<StoredSession> | null = null;
let sessionExpiredHandler: (() => void) | null = null;

/** Registered by AuthProvider so the UI can react when a session can no longer be renewed. */
export function setSessionExpiredHandler(handler: (() => void) | null) {
  sessionExpiredHandler = handler;
}

/**
 * The backend rotates refresh tokens (the old one is revoked on use), so concurrent
 * 401s must share a single refresh call.
 */
export function refreshSession(): Promise<StoredSession> {
  if (refreshPromise) return refreshPromise;
  const current = tokenStorage.get();
  if (!current) {
    return Promise.reject(new AppError({ kind: "unauthorized", status: 401, userMessage: MESSAGES.unauthorized }));
  }
  refreshPromise = apiClient
    .post<TokenPairResponse>(
      `/${current.channel}/auth/token/refresh`,
      { refresh_token: current.refreshToken, device_id: WEB_DEVICE.device_id },
      { skipAuth: true, skipAuthRefresh: true }
    )
    .then(({ data }) => {
      // The user may have signed out while the refresh was in flight.
      if (tokenStorage.get()?.refreshToken !== current.refreshToken) {
        throw new AppError({ kind: "unauthorized", status: 401, userMessage: MESSAGES.unauthorized });
      }
      const next: StoredSession = {
        channel: current.channel,
        accessToken: data.access_token,
        refreshToken: data.refresh_token
      };
      tokenStorage.set(next);
      return next;
    })
    .finally(() => {
      refreshPromise = null;
    });
  return refreshPromise;
}

function bearer(token: string) {
  return `Bearer ${token}`;
}

apiClient.interceptors.request.use((config) => {
  if (!config.skipAuth && !config.headers.Authorization) {
    const session = tokenStorage.get();
    if (session) config.headers.Authorization = bearer(session.accessToken);
  }
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    const config = axios.isAxiosError(error) ? (error.config as InternalAxiosRequestConfig | undefined) : undefined;
    const isExpired = axios.isAxiosError(error) && error.response?.status === 401;
    const session = tokenStorage.get();

    if (isExpired && config && session && !config.skipAuth && !config.skipAuthRefresh && !config._retried) {
      config._retried = true;
      const usedToken = String(config.headers.Authorization ?? "");
      let next: StoredSession;
      try {
        // Another request may already have renewed the session.
        next = usedToken === bearer(session.accessToken) ? await refreshSession() : session;
      } catch (refreshError) {
        const appError = normalizeError(refreshError);
        // A connectivity problem is not a reason to sign the user out.
        if (appError.kind === "network" || appError.kind === "timeout" || appError.kind === "server") {
          throw appError;
        }
        if (tokenStorage.get()?.refreshToken === session.refreshToken) {
          tokenStorage.clear();
        }
        sessionExpiredHandler?.();
        throw new AppError({
          kind: "unauthorized",
          status: 401,
          code: "SESSION_EXPIRED",
          userMessage: MESSAGES.unauthorized
        });
      }
      config.headers.Authorization = bearer(next.accessToken);
      return apiClient(config);
    }

    throw normalizeError(error);
  }
);
