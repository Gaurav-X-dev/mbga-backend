import axios from "axios";

import { env } from "../config/env";

/**
 * The backend's own OpenAPI document, per channel.
 *
 * Served from the server root (`/openapi/admin.json`), not from the API prefix, so this uses
 * a bare axios call rather than `apiClient`: the schema is public, needs no access token, and
 * must not be retried through the session-refresh interceptor.
 */
export type ApiChannel = "admin" | "merchant" | "customer" | "delivery" | "internal";

export type OpenApiParameter = {
  name: string;
  in: "path" | "query" | "header" | "cookie";
  required?: boolean;
  description?: string;
  schema?: { type?: string; format?: string; enum?: string[]; default?: unknown; items?: { type?: string } };
};

export type OpenApiOperation = {
  summary?: string;
  description?: string;
  operationId?: string;
  tags?: string[];
  parameters?: OpenApiParameter[];
  requestBody?: {
    required?: boolean;
    content?: Record<string, { schema?: Record<string, unknown> }>;
  };
  responses?: Record<string, { description?: string }>;
  deprecated?: boolean;
};

export type OpenApiDocument = {
  openapi: string;
  info: { title: string; version: string };
  paths: Record<string, Record<string, OpenApiOperation>>;
  components?: { schemas?: Record<string, Record<string, unknown>> };
};

/** The server root, derived from the API base URL by dropping its path. */
export function serverOrigin(): string {
  try {
    return new URL(env.apiBaseUrl).origin;
  } catch {
    // A relative base URL (same-origin deployment) resolves against the page.
    return window.location.origin;
  }
}

/** The path prefix the API is mounted under, e.g. "/api/v1". */
export function apiPrefix(): string {
  try {
    return new URL(env.apiBaseUrl).pathname.replace(/\/+$/, "");
  } catch {
    return env.apiBaseUrl.replace(/\/+$/, "");
  }
}

export async function fetchOpenApi(channel: ApiChannel, signal?: AbortSignal) {
  const { data } = await axios.get<OpenApiDocument>(`${serverOrigin()}/openapi/${channel}.json`, {
    signal,
    timeout: 20_000
  });
  return data;
}
