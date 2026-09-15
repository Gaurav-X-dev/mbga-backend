export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1",
  previewMode: import.meta.env.VITE_ENABLE_PREVIEW_MODE === "true"
};
