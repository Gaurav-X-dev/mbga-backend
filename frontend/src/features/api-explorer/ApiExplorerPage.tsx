import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import type { ReactNode } from "react";

import { apiClient } from "../../api/client";
import { normalizeError } from "../../api/errors";
import {
  apiPrefix,
  fetchOpenApi,
  serverOrigin,
  type ApiChannel,
  type OpenApiDocument,
  type OpenApiOperation,
  type OpenApiParameter
} from "../../api/openapi.api";
import { Button } from "../../components/common/Button";
import { Badge } from "../../components/common/StatusBadge";
import { EmptyState, ErrorState, LoadingSkeleton } from "../../components/feedback/Feedback";
import { Field, Input, SearchInput, Select, Textarea } from "../../components/forms/Field";
import { Card, MiniStat, PageHeader } from "../../components/layout/Page";

/*
 * A request console for this backend, driven by its own OpenAPI document.
 *
 * It lists nothing of its own: the endpoint list, the parameters and the documented responses
 * all come from `/openapi/<channel>.json`, so a route added to the API shows up here without
 * anyone remembering to update a list. Requests go through the app's `apiClient`, which means
 * they carry the signed-in session and behave exactly as the rest of the panel's calls do.
 */

const CHANNELS: Array<{ value: ApiChannel; label: string }> = [
  { value: "admin", label: "Admin" },
  { value: "merchant", label: "Merchant" },
  { value: "customer", label: "Customer" },
  { value: "delivery", label: "Delivery" },
  { value: "internal", label: "All channels" }
];

const METHOD_ORDER = ["get", "post", "put", "patch", "delete"];

type Endpoint = {
  id: string;
  path: string;
  method: string;
  operation: OpenApiOperation;
  tag: string;
};

type RunResult = {
  status: number | null;
  statusText: string;
  durationMs: number;
  body: unknown;
  headers: Record<string, string>;
  requestUrl: string;
  errorMessage?: string;
};

function methodTone(method: string) {
  if (method === "get") return "info";
  if (method === "post") return "success";
  if (method === "delete") return "danger";
  return "warning";
}

function statusTone(status: number | null) {
  if (status === null) return "danger";
  if (status < 300) return "success";
  if (status < 400) return "info";
  if (status < 500) return "warning";
  return "danger";
}

/** Flattens the schema into one endpoint per path+method, tagged for grouping. */
function toEndpoints(document: OpenApiDocument | undefined): Endpoint[] {
  if (!document) return [];
  const list: Endpoint[] = [];
  for (const [path, operations] of Object.entries(document.paths ?? {})) {
    for (const [method, operation] of Object.entries(operations)) {
      if (!METHOD_ORDER.includes(method.toLowerCase())) continue;
      list.push({
        id: `${method}:${path}`,
        path,
        method: method.toLowerCase(),
        operation,
        tag: operation.tags?.[0] ?? "Other"
      });
    }
  }
  return list.sort(
    (a, b) =>
      a.tag.localeCompare(b.tag) ||
      a.path.localeCompare(b.path) ||
      METHOD_ORDER.indexOf(a.method) - METHOD_ORDER.indexOf(b.method)
  );
}

/** A starter JSON body from the operation's request schema, so the box is never blank. */
function exampleBody(operation: OpenApiOperation, document: OpenApiDocument | undefined): string {
  const schema = operation.requestBody?.content?.["application/json"]?.schema;
  if (!schema) return "";
  const resolved = resolveSchema(schema, document);
  const properties = (resolved?.properties ?? {}) as Record<string, Record<string, unknown>>;
  const required = new Set((resolved?.required as string[] | undefined) ?? []);
  const draft: Record<string, unknown> = {};
  for (const [name, property] of Object.entries(properties)) {
    // Only the required fields: a body full of nulls is more noise than help.
    if (required.size > 0 && !required.has(name)) continue;
    draft[name] = placeholderFor(property);
  }
  return Object.keys(draft).length > 0 ? JSON.stringify(draft, null, 2) : "{}";
}

function resolveSchema(
  schema: Record<string, unknown> | undefined,
  document: OpenApiDocument | undefined
): Record<string, unknown> | undefined {
  if (!schema) return undefined;
  const ref = schema.$ref as string | undefined;
  if (!ref) return schema;
  const name = ref.split("/").pop();
  if (!name) return schema;
  return document?.components?.schemas?.[name];
}

function placeholderFor(property: Record<string, unknown>): unknown {
  const type = property.type as string | undefined;
  if (Array.isArray(property.enum) && property.enum.length > 0) return property.enum[0];
  if (type === "integer" || type === "number") return 0;
  if (type === "boolean") return false;
  if (type === "array") return [];
  if (type === "object") return {};
  return "";
}

function ParamFields({
  parameters,
  values,
  onChange,
  kind
}: {
  parameters: OpenApiParameter[];
  values: Record<string, string>;
  onChange: (name: string, value: string) => void;
  kind: "path" | "query";
}) {
  const list = parameters.filter((parameter) => parameter.in === kind);
  if (list.length === 0) return null;
  return (
    <div className="form-grid">
      {list.map((parameter) => {
        const options = parameter.schema?.enum;
        return (
          <Field
            key={parameter.name}
            label={parameter.name}
            required={kind === "path" || parameter.required}
            hint={parameter.description}
          >
            {options && options.length > 0 ? (
              <Select
                value={values[parameter.name] ?? ""}
                onChange={(event) => onChange(parameter.name, event.target.value)}
                placeholder="—"
                options={options.map((option) => ({ value: String(option), label: String(option) }))}
              />
            ) : (
              <Input
                value={values[parameter.name] ?? ""}
                placeholder={parameter.schema?.type ?? "string"}
                onChange={(event) => onChange(parameter.name, event.target.value)}
              />
            )}
          </Field>
        );
      })}
    </div>
  );
}

function ResultPanel({ result }: { result: RunResult }) {
  const tone = statusTone(result.status);
  return (
    <div className="stack">
      <div className="row-between">
        <div className="row">
          <Badge tone={tone} plain={false}>
            {result.status === null ? "No response" : `${result.status} ${result.statusText}`.trim()}
          </Badge>
          <span className="meta">{Math.round(result.durationMs)} ms</span>
        </div>
        <span className="meta mono">{result.requestUrl}</span>
      </div>
      {result.errorMessage ? <p className="text-small">{result.errorMessage}</p> : null}
      <div>
        <p className="eyebrow" style={{ marginBottom: 6 }}>
          Response body
        </p>
        <pre className="code-block">
          {typeof result.body === "string" ? result.body : JSON.stringify(result.body, null, 2)}
        </pre>
      </div>
      {Object.keys(result.headers).length > 0 ? (
        <div>
          <p className="eyebrow" style={{ marginBottom: 6 }}>
            Response headers
          </p>
          <pre className="code-block">
            {Object.entries(result.headers)
              .map(([name, value]) => `${name}: ${value}`)
              .join("\n")}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

export function ApiExplorerPage() {
  const [channel, setChannel] = useState<ApiChannel>("admin");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pathValues, setPathValues] = useState<Record<string, string>>({});
  const [queryValues, setQueryValues] = useState<Record<string, string>>({});
  const [body, setBody] = useState("");
  const [bodyError, setBodyError] = useState<string | undefined>();
  const [result, setResult] = useState<RunResult | null>(null);
  const [running, setRunning] = useState(false);

  const schema = useQuery({
    queryKey: ["api-explorer", "openapi", channel],
    queryFn: ({ signal }) => fetchOpenApi(channel, signal),
    staleTime: 5 * 60_000,
    retry: false
  });

  const endpoints = useMemo(() => toEndpoints(schema.data), [schema.data]);
  const term = search.trim().toLowerCase();
  const visible = endpoints.filter(
    (endpoint) =>
      !term ||
      endpoint.path.toLowerCase().includes(term) ||
      endpoint.method.includes(term) ||
      endpoint.tag.toLowerCase().includes(term) ||
      (endpoint.operation.summary ?? "").toLowerCase().includes(term)
  );
  const grouped = useMemo(() => {
    const map = new Map<string, Endpoint[]>();
    for (const endpoint of visible) {
      const list = map.get(endpoint.tag) ?? [];
      list.push(endpoint);
      map.set(endpoint.tag, list);
    }
    return [...map.entries()];
  }, [visible]);

  const selected = endpoints.find((endpoint) => endpoint.id === selectedId) ?? null;
  const parameters = selected?.operation.parameters ?? [];

  function select(endpoint: Endpoint) {
    setSelectedId(endpoint.id);
    setResult(null);
    setBodyError(undefined);
    setPathValues({});
    // Pre-fill query defaults from the schema so a GET is runnable straight away.
    const defaults: Record<string, string> = {};
    for (const parameter of endpoint.operation.parameters ?? []) {
      if (parameter.in === "query" && parameter.schema?.default !== undefined) {
        defaults[parameter.name] = String(parameter.schema.default);
      }
    }
    setQueryValues(defaults);
    setBody(exampleBody(endpoint.operation, schema.data));
  }

  /** Substitutes `{placeholders}` and appends the non-empty query values. */
  function buildUrl(endpoint: Endpoint): string {
    let path = endpoint.path;
    for (const [name, value] of Object.entries(pathValues)) {
      path = path.replace(`{${name}}`, encodeURIComponent(value));
    }
    // The document's paths include the API prefix; apiClient adds it too, so drop it here.
    const prefix = apiPrefix();
    if (prefix && path.startsWith(prefix)) path = path.slice(prefix.length);
    const query = new URLSearchParams();
    for (const [name, value] of Object.entries(queryValues)) {
      if (value !== "") query.set(name, value);
    }
    const search = query.toString();
    return search ? `${path}?${search}` : path;
  }

  async function run() {
    if (!selected) return;
    const missing = parameters
      .filter((parameter) => parameter.in === "path")
      .find((parameter) => !(pathValues[parameter.name] ?? "").trim());
    if (missing) {
      setResult({
        status: null,
        statusText: "",
        durationMs: 0,
        body: `Fill in the path parameter "${missing.name}" first.`,
        headers: {},
        requestUrl: selected.path
      });
      return;
    }

    let parsedBody: unknown;
    const needsBody = selected.method !== "get" && selected.method !== "delete" && body.trim() !== "";
    if (needsBody) {
      try {
        parsedBody = JSON.parse(body);
        setBodyError(undefined);
      } catch (error) {
        setBodyError(error instanceof Error ? error.message : "The body is not valid JSON.");
        return;
      }
    }

    const url = buildUrl(selected);
    const startedAt = performance.now();
    setRunning(true);
    try {
      const response = await apiClient.request({
        url,
        method: selected.method,
        data: needsBody ? parsedBody : undefined,
        // The console reports failures rather than throwing them, and must not trigger the
        // session-refresh retry: a 401 here is a result worth seeing, not an error to hide.
        validateStatus: () => true,
        skipAuthRefresh: true
      });
      setResult({
        status: response.status,
        statusText: response.statusText,
        durationMs: performance.now() - startedAt,
        body: response.data,
        headers: Object.fromEntries(
          Object.entries(response.headers ?? {}).map(([name, value]) => [name, String(value)])
        ),
        requestUrl: `${serverOrigin()}${apiPrefix()}${url}`
      });
    } catch (error) {
      const appError = normalizeError(error);
      setResult({
        status: null,
        statusText: "",
        durationMs: performance.now() - startedAt,
        body: appError.userMessage,
        headers: {},
        requestUrl: `${serverOrigin()}${apiPrefix()}${url}`,
        errorMessage: "The request never completed — the server could not be reached or timed out."
      });
    } finally {
      setRunning(false);
    }
  }

  const documentedResponses: ReactNode = selected ? (
    <div className="tag-list">
      {Object.entries(selected.operation.responses ?? {}).map(([code, response]) => (
        <Badge key={code} tone={statusTone(Number(code) || null)} plain={false}>
          {code} {response.description ?? ""}
        </Badge>
      ))}
    </div>
  ) : null;

  return (
    <div className="page api-explorer">
      <PageHeader
        title="API Console"
        documentTitle="API Console"
        eyebrow="Developer tools"
        description="Every endpoint this backend exposes, read from its own OpenAPI document. Send a request and see the status code, timing and full response."
        actions={
          <Field label="Channel" hideLabel>
            <Select
              value={channel}
              onChange={(event) => {
                setChannel(event.target.value as ApiChannel);
                setSelectedId(null);
                setResult(null);
              }}
              options={CHANNELS}
            />
          </Field>
        }
      />

      {schema.isLoading ? (
        <Card>
          <LoadingSkeleton rows={5} label="Loading the API schema" />
        </Card>
      ) : schema.error ? (
        <Card>
          <ErrorState
            error={schema.error}
            title="The API schema could not be loaded"
            onRetry={() => void schema.refetch()}
          />
          <p className="meta" style={{ textAlign: "center" }}>
            Looked for {serverOrigin()}/openapi/{channel}.json — the server must be running with docs enabled.
          </p>
        </Card>
      ) : (
        <>
          <div className="mini-stat-strip" aria-label="API summary">
            <MiniStat label="Endpoints" value={endpoints.length} icon="code" tone="blue" />
            <MiniStat label="Groups" value={new Set(endpoints.map((item) => item.tag)).size} icon="box" tone="violet" />
            <MiniStat label="Showing" value={visible.length} icon="filter" tone="green" />
            <MiniStat label="Schema" value={schema.data?.info.version ?? "—"} icon="fileText" tone="slate" />
          </div>

          <div className="api-explorer__layout">
            <Card bodyless className="api-explorer__list">
              <div className="filter-bar">
                <div className="filter-bar__fields">
                  <SearchInput
                    label="Search endpoints"
                    placeholder="Search by path, method or group"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                  />
                </div>
              </div>
              <div className="api-list">
                {grouped.length === 0 ? (
                  <EmptyState icon="search" title="No endpoints match" description="Try a different path or method." />
                ) : (
                  grouped.map(([tag, items]) => (
                    <section key={tag} className="api-group">
                      <h2 className="api-group__title">
                        {tag}
                        <span className="tab-count">{items.length}</span>
                      </h2>
                      <ul className="list-plain">
                        {items.map((endpoint) => (
                          <li key={endpoint.id}>
                            <button
                              type="button"
                              className={`api-row${endpoint.id === selectedId ? " is-active" : ""}`}
                              onClick={() => select(endpoint)}
                            >
                              <span className={`api-method api-method--${methodTone(endpoint.method)}`}>
                                {endpoint.method}
                              </span>
                              <span className="api-row__text">
                                <span className="api-row__path">{endpoint.path}</span>
                                {endpoint.operation.summary ? (
                                  <small>{endpoint.operation.summary}</small>
                                ) : null}
                              </span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    </section>
                  ))
                )}
              </div>
            </Card>

            <div className="api-explorer__detail">
              {!selected ? (
                <Card>
                  <EmptyState
                    icon="code"
                    title="Pick an endpoint"
                    description="Choose a request on the left to see its parameters and send it against the running server."
                  />
                </Card>
              ) : (
                <div className="stack">
                  <Card
                    title={
                      <>
                        <span className={`api-method api-method--${methodTone(selected.method)}`}>
                          {selected.method}
                        </span>
                        <span className="mono">{selected.path}</span>
                      </>
                    }
                    subtitle={selected.operation.summary}
                    actions={
                      <Button variant="primary" icon="zap" onClick={() => void run()} loading={running} loadingText="Sending…">
                        Send
                      </Button>
                    }
                  >
                    <div className="stack">
                      {selected.operation.description ? (
                        <p className="text-small text-muted">{selected.operation.description}</p>
                      ) : null}

                      {parameters.some((parameter) => parameter.in === "path") ? (
                        <div className="stack" style={{ gap: "var(--space-2)" }}>
                          <p className="eyebrow">Path parameters</p>
                          <ParamFields parameters={parameters} values={pathValues} kind="path" onChange={(name, value) => setPathValues((previous) => ({ ...previous, [name]: value }))} />
                        </div>
                      ) : null}

                      {parameters.some((parameter) => parameter.in === "query") ? (
                        <div className="stack" style={{ gap: "var(--space-2)" }}>
                          <p className="eyebrow">Query parameters</p>
                          <ParamFields parameters={parameters} values={queryValues} kind="query" onChange={(name, value) => setQueryValues((previous) => ({ ...previous, [name]: value }))} />
                        </div>
                      ) : null}

                      {selected.method !== "get" && selected.method !== "delete" ? (
                        <Field
                          label="Request body (JSON)"
                          error={bodyError}
                          hint="Pre-filled with the required fields from the schema."
                        >
                          <Textarea
                            className="mono"
                            rows={10}
                            value={body}
                            onChange={(event) => {
                              setBody(event.target.value);
                              setBodyError(undefined);
                            }}
                          />
                        </Field>
                      ) : null}

                      {documentedResponses ? (
                        <div className="stack" style={{ gap: "var(--space-2)" }}>
                          <p className="eyebrow">Documented responses</p>
                          {documentedResponses}
                        </div>
                      ) : null}
                    </div>
                  </Card>

                  {result ? (
                    <Card title="Response">
                      <ResultPanel result={result} />
                    </Card>
                  ) : null}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
