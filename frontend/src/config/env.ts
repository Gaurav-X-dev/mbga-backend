/**
 * Public browser configuration only. Never put secrets in VITE_ variables:
 * everything here is bundled into the JavaScript served to every visitor.
 */
function readApiBaseUrl(): string {
  const value = import.meta.env.VITE_API_BASE_URL;
  if (!value) {
    if (import.meta.env.DEV || import.meta.env.MODE === "test") {
      return "http://127.0.0.1:8005/api/v1";
    }
    throw new Error("VITE_API_BASE_URL is not configured");
  }
  return value.replace(/\/+$/, "");
}

export const env = {
  apiBaseUrl: readApiBaseUrl(),
  /** Local preview helpers (for example the development verification code hint). */
  previewMode: import.meta.env.VITE_ENABLE_PREVIEW_MODE === "true"
};
