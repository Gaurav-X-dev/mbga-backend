export type AuthChannel = "admin" | "merchant";

export type StoredSession = {
  channel: AuthChannel;
  accessToken: string;
  refreshToken: string;
};

/**
 * The backend issues bearer tokens in the response body (no HttpOnly cookie option),
 * so the session is kept in sessionStorage: it survives a page reload, is scoped to
 * the browser tab and is discarded when the tab closes. Only this key is owned by the
 * app; sign-out removes it and nothing else.
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
    const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isStoredSession(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export const tokenStorage = {
  get(): StoredSession | null {
    if (cache === undefined) cache = read();
    return cache;
  },
  set(session: StoredSession) {
    cache = session;
    try {
      window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
    } catch {
      // Storage can be unavailable (private mode); the in-memory session still works for this page.
    }
    listeners.forEach((listener) => listener(session));
  },
  clear() {
    cache = null;
    try {
      window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
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
