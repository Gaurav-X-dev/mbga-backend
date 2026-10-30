export type AuthChannel = "admin" | "merchant";

export type StoredSession = {
  channel: AuthChannel;
  accessToken: string;
  refreshToken: string;
};

/**
 * The backend issues bearer tokens in the response body (no HttpOnly cookie option),
 * so the session is kept in localStorage: it survives a page reload, is shared by every
 * tab on this browser, and outlives the tab that signed in. Only this key is owned by the
 * app; sign-out removes it and nothing else.
 *
 * It was sessionStorage, which is per tab - opening the panel in a second tab asked the
 * operator to sign in again, with an OTP, while the first tab sat there signed in. That
 * is the cost being traded away: the session now also survives closing the browser, so on
 * a shared machine the next person finds the panel open until the token expires.
 */
export const SESSION_STORAGE_KEY = "mbga.web.session.v1";

let cache: StoredSession | null | undefined;
const listeners = new Set<(session: StoredSession | null) => void>();

function isStoredSession(value: unknown): value is StoredSession {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Record<string, unknown>;
  return (
    (candidate.channel === "admin" || candidate.channel === "merchant") &&
    typeof candidate.accessToken === "string" &&
    typeof candidate.refreshToken === "string"
  );
}

function read(): StoredSession | null {
  try {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isStoredSession(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

// Shared storage means a second tab can sign in or out underneath this one. Without this
// the other tab keeps rendering the app until its next request fails, which reads as the
// sign-out not having worked.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (event.key !== SESSION_STORAGE_KEY) return;
    cache = read();
    listeners.forEach((listener) => listener(cache ?? null));
  });
}

export const tokenStorage = {
  get(): StoredSession | null {
    if (cache === undefined) cache = read();
    return cache;
  },
  set(session: StoredSession) {
    cache = session;
    try {
      window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
    } catch {
      // Storage can be unavailable (private mode); the in-memory session still works for this page.
    }
    listeners.forEach((listener) => listener(session));
  },
  clear() {
    cache = null;
    try {
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
    } catch {
      // ignore
    }
    listeners.forEach((listener) => listener(null));
  },
  subscribe(listener: (session: StoredSession | null) => void) {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  /** Test helper: forget the in-memory copy so the next read goes to storage. */
  resetCache() {
    cache = undefined;
  }
};
