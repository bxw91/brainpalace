import {
  Instance,
  UiSchema,
  InstanceStatusPayload,
  type ConfigValues,
  type EffectiveConfig,
  type FoldersPayload,
  type DocumentsPayload,
  type DocumentChunksPayload,
  type IngestSourcesPayload,
  type IngestChunksPayload,
  type JobsPayload,
  type JobDetail,
  type CachePayload,
  type CacheHistoryPayload,
  type CacheEconomics,
  type MemoriesPayload,
  type SessionArchivePayload,
  type DecisionNode,
  type TimelineRow,
  type QueryRow,
  type QueryDetail,
  type QueryStats,
  type ReplayResponse,
  type LogsPayload,
  type UnsetResult,
  type GraphNodeHit,
  type GraphSubgraph,
  type GraphNodeSource,
  type GraphImpactNode,
  type GraphCochangeFile,
  type ProviderTestResult,
} from "./types";

const BASE = "/dashboard/api";

/** Thrown when an instance is stopped/unreachable (upstream 502 from the BFF). */
export class InstanceUnreachableError extends Error {
  upstreamStatus?: number;
  constructor(message: string, upstreamStatus?: number) {
    super(message);
    this.name = "InstanceUnreachableError";
    this.upstreamStatus = upstreamStatus;
  }
}

async function readError(r: Response): Promise<unknown> {
  return r
    .clone()
    .json()
    .catch(() => ({}));
}

async function get<T>(path: string, parse: (j: unknown) => T): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) {
    const body = (await readError(r)) as Record<string, unknown>;
    throw new Error((body?.detail as string) ?? r.statusText);
  }
  return parse(await r.json());
}

export const listInstances = () =>
  get("/instances", (j) => Instance.array().parse(j));

export const getSchema = () => get("/schema", (j) => UiSchema.parse(j));

export const getConfig = (id: string) =>
  get(`/instances/${id}/config`, (j) => j as ConfigValues);

export const getConfigEffective = (id: string) =>
  get(`/instances/${id}/config/effective`, (j) => j as EffectiveConfig);

/** Per-instance status. Throws InstanceUnreachableError on a 502 (server down). */
export async function getInstanceStatus(
  id: string,
): Promise<InstanceStatusPayload> {
  const r = await fetch(`${BASE}/instances/${id}/status`);
  if (r.status === 502) {
    const body = (await readError(r)) as Record<string, unknown>;
    throw new InstanceUnreachableError(
      (body?.detail as string) ?? "instance unreachable",
      body?.upstream_status as number | undefined,
    );
  }
  if (!r.ok) {
    const body = (await readError(r)) as Record<string, unknown>;
    throw new Error((body?.detail as string) ?? r.statusText);
  }
  return InstanceStatusPayload.parse(await r.json());
}

export type InstanceHealth = {
  status?: string;
  version?: string;
  mode?: string;
  project_root?: string;
};

/** Liveness + server version. Throws InstanceUnreachableError on a 502. */
export const getInstanceHealth = (id: string): Promise<InstanceHealth> =>
  getData<InstanceHealth>(`/instances/${id}/health`);

export async function patchConfig(
  id: string,
  values: ConfigValues,
  restart: boolean,
  forceReindex = false,
  unset: string[] = [],
): Promise<{ ok: boolean; restarted?: boolean; reindex_triggered?: number }> {
  const r = await fetch(`${BASE}/instances/${id}/config`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ values, unset, restart, force_reindex: forceReindex }),
  });
  if (!r.ok) {
    // 422 -> { errors: [...] }; 409 -> DataConflictEnvelope { conflict, ... }
    throw await readError(r);
  }
  return r.json();
}

/**
 * Remove project-level keys so they inherit from global / code default. Returns
 * the removed keys plus the NEW effective value+source per requested key.
 */
export async function unsetConfig(
  id: string,
  dotpaths: string[],
): Promise<UnsetResult> {
  const r = await fetch(`${BASE}/instances/${id}/config/unset`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ dotpaths }),
  });
  if (!r.ok) throw await readError(r);
  return r.json();
}

// ---------------------------------------------------------------------------
// Global config — the global XDG config.yaml (every project inherits it).
// The provenance layer here is global-file > code default.
// ---------------------------------------------------------------------------

export const getGlobalConfig = () =>
  get("/global-config", (j) => j as ConfigValues);

export async function patchGlobalConfig(
  values: ConfigValues,
  forceReindex = false,
  unset: string[] = [],
): Promise<{ ok: boolean }> {
  const r = await fetch(`${BASE}/global-config`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      values,
      unset,
      restart: false,
      force_reindex: forceReindex,
    }),
  });
  if (!r.ok) throw await readError(r); // 422 -> { errors }; 409 -> conflict
  return r.json();
}

export const getGlobalConfigEffective = () =>
  get("/global-config/effective", (j) => j as EffectiveConfig);

/** Remove keys from the global config.yaml so they fall back to code default. */
export async function unsetGlobalConfig(
  dotpaths: string[],
): Promise<UnsetResult> {
  const r = await fetch(`${BASE}/global-config/unset`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ dotpaths }),
  });
  if (!r.ok) throw await readError(r);
  return r.json();
}

// ---------------------------------------------------------------------------
// Control-plane ("server") settings — the dashboard's own config, distinct from
// per-instance config. (`dashboard:` block in the XDG config.yaml.)
// ---------------------------------------------------------------------------

export type TimeFormat = "24h" | "12h";
export type DateFormat = "dd.mm.yyyy" | "mm.dd.yyyy" | "yyyy-mm-dd";

export type DashboardSettings = {
  host: string;
  port: number;
  poll_s: number;
  autostart: boolean;
  time_format: TimeFormat;
  date_format: DateFormat;
  token_set: boolean;
  token: string;
  version: string;
  runtime: { running: boolean; port?: number; base_url?: string };
};

export const getSettings = (): Promise<DashboardSettings> =>
  getData<DashboardSettings>("/settings");

/** PyPI update status driving the "new version" banner. */
export type UpdateStatus = {
  current: string;
  latest: string | null;
  update_available: boolean;
  package: string;
  checked_at: number;
};

export const getUpdateCheck = (): Promise<UpdateStatus> =>
  getData<UpdateStatus>("/settings/update-check");

export async function patchSettings(
  values: Record<string, unknown>,
  unset: string[] = [],
): Promise<{ ok: boolean; restart_required: string[] }> {
  const r = await fetch(`${BASE}/settings`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ ...values, unset }),
  });
  if (!r.ok) throw await readError(r); // 422 -> { errors: [...] }
  return r.json();
}

export type SettingsEffective = Record<
  string,
  { value: unknown; source: "file" | "default" }
>;

export const getSettingsEffective = (): Promise<SettingsEffective> =>
  getData<SettingsEffective>("/settings/effective");

export async function unsetSettings(
  fields: string[],
): Promise<{ removed: string[]; effective: SettingsEffective }> {
  const r = await fetch(`${BASE}/settings/unset`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ fields }),
  });
  if (!r.ok) throw await readError(r);
  return r.json();
}

const post = (path: string) =>
  fetch(`${BASE}${path}`, { method: "POST" }).then((r) => r.json());

export const startInstance = (id: string) => post(`/instances/${id}/start`);
export const stopInstance = (id: string) => post(`/instances/${id}/stop`);
export const restartInstance = (id: string) => post(`/instances/${id}/restart`);

export const registerProject = (path: string) =>
  fetch(`${BASE}/instances/register`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ path }),
  }).then((r) => r.json());

export const forgetInstance = (id: string) =>
  fetch(`${BASE}/instances/${id}`, { method: "DELETE" }).then((r) => r.json());

// ---------------------------------------------------------------------------
// Per-instance data reads + action proxies (Phase 06).
//
// Reads use `getData` which surfaces a stopped/unreachable server as an
// `InstanceUnreachableError` (upstream 502) so each data tab can render its
// clean "stopped — Start" empty state instead of crashing. The BFF normalizes
// every upstream failure to `{error, detail, upstream_status}`.
// ---------------------------------------------------------------------------

async function getData<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (r.status === 502) {
    const body = (await readError(r)) as Record<string, unknown>;
    throw new InstanceUnreachableError(
      (body?.detail as string) ?? "instance unreachable",
      body?.upstream_status as number | undefined,
    );
  }
  if (!r.ok) {
    const body = (await readError(r)) as Record<string, unknown>;
    throw new Error((body?.detail as string) ?? r.statusText);
  }
  return (await r.json()) as T;
}

/** Action POST/DELETE that surfaces a 502 as InstanceUnreachableError. */
async function actData<T>(
  path: string,
  method: "POST" | "DELETE",
  body?: unknown,
): Promise<T> {
  const init: RequestInit = { method };
  if (body !== undefined) {
    init.headers = { "content-type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const r = await fetch(`${BASE}${path}`, init);
  if (r.status === 502) {
    const err = (await readError(r)) as Record<string, unknown>;
    throw new InstanceUnreachableError(
      (err?.detail as string) ?? "instance unreachable",
      err?.upstream_status as number | undefined,
    );
  }
  if (!r.ok) {
    const err = (await readError(r)) as Record<string, unknown>;
    throw new Error((err?.detail as string) ?? r.statusText);
  }
  return (await r.json()) as T;
}

// ---- reads ----
export const getFolders = (id: string) =>
  getData<FoldersPayload>(`/instances/${id}/folders`);
export const getJobs = (id: string, showAll = false) =>
  getData<JobsPayload>(`/instances/${id}/jobs${showAll ? "?all=1" : ""}`);
export const getJobDetail = (id: string, jobId: string) =>
  getData<JobDetail>(`/instances/${id}/jobs/${jobId}`);
export const getCache = (id: string) =>
  getData<CachePayload>(`/instances/${id}/cache`);
export const getCacheHistory = (id: string, since?: number) => {
  const p = since != null ? `?since=${since}` : "";
  return getData<CacheHistoryPayload>(`/instances/${id}/cache/history${p}`);
};
export const getCacheEconomics = (id: string) =>
  getData<CacheEconomics>(`/instances/${id}/cache/economics`);
export const getMemories = (id: string) =>
  getData<MemoriesPayload>(`/instances/${id}/memories`);

export const getSessionArchive = (id: string) =>
  getData<SessionArchivePayload>(`/instances/${id}/sessions/archive`);

export const getDecisions = (id: string, contains?: string, limit = 50) => {
  const p = new URLSearchParams({ limit: String(limit) });
  if (contains) p.set("contains", contains);
  return getData<{ decisions: DecisionNode[] }>(
    `/instances/${id}/sessions/decisions?${p.toString()}`,
  );
};

export const getDecisionTimeline = (id: string, entity: string) =>
  getData<{ entity: string; timeline: TimelineRow[] }>(
    `/instances/${id}/sessions/timeline?${new URLSearchParams({ entity })}`,
  );

export function getDocuments(
  id: string,
  q: { folder: string; contains?: string; limit?: number; offset?: number },
): Promise<DocumentsPayload> {
  const p = new URLSearchParams(
    Object.entries(q)
      .filter(([, v]) => v != null && v !== "")
      .map(([k, v]) => [k, String(v)]),
  );
  return getData<DocumentsPayload>(`/instances/${id}/documents?${p.toString()}`);
}

export const getDocumentChunks = (
  id: string,
  folder: string,
  path: string,
  limit = 50,
): Promise<DocumentChunksPayload> => {
  const p = new URLSearchParams({ folder, path, limit: String(limit) });
  return getData<DocumentChunksPayload>(
    `/instances/${id}/documents/chunks?${p.toString()}`,
  );
};

export const getIngestSources = (id: string): Promise<IngestSourcesPayload> =>
  getData<IngestSourcesPayload>(`/instances/${id}/ingest/sources`);

export const getIngestChunks = (
  id: string,
  q: { source_id: string; offset?: number; limit?: number },
): Promise<IngestChunksPayload> => {
  const p = new URLSearchParams(
    Object.entries(q)
      .filter(([, v]) => v != null && v !== "")
      .map(([k, v]) => [k, String(v)]),
  );
  return getData<IngestChunksPayload>(`/instances/${id}/ingest/chunks?${p.toString()}`);
};

export function getQueries(
  id: string,
  q: {
    mode?: string;
    contains?: string;
    since?: number;
    limit?: number;
    offset?: number;
  } = {},
): Promise<QueryRow[]> {
  const p = new URLSearchParams(
    Object.entries(q)
      .filter(([, v]) => v != null && v !== "")
      .map(([k, v]) => [k, String(v)]),
  );
  return getData<QueryRow[]>(`/instances/${id}/queries?${p.toString()}`);
}

export const getQueryDetail = (id: string, qid: string) =>
  getData<QueryDetail>(`/instances/${id}/queries/${qid}`);

export function getQueryStats(
  id: string,
  q: { since?: number; top_n?: number } = {},
): Promise<QueryStats> {
  const p = new URLSearchParams(
    Object.entries(q)
      .filter(([, v]) => v != null)
      .map(([k, v]) => [k, String(v)]),
  );
  return getData<QueryStats>(`/instances/${id}/queries/stats?${p.toString()}`);
}

export const getLogs = async (
  id: string,
  lines = 200,
  level?: string,
): Promise<LogsPayload> => {
  const p = new URLSearchParams({ lines: String(lines) });
  if (level) p.set("level", level);
  const r = await fetch(`${BASE}/instances/${id}/logs?${p.toString()}`);
  if (r.status === 502) {
    const body = (await readError(r)) as Record<string, unknown>;
    throw new InstanceUnreachableError(
      (body?.detail as string) ?? "instance unreachable",
      body?.upstream_status as number | undefined,
    );
  }
  // Older project servers (or fresh ones with no log file yet) 404 on
  // /health/logs. Treat that as "log tailing unavailable" rather than a hard
  // error so the tab degrades gracefully.
  if (r.status === 404) return { lines: [], unavailable: true };
  if (!r.ok) {
    const body = (await readError(r)) as Record<string, unknown>;
    throw new Error((body?.detail as string) ?? r.statusText);
  }
  return (await r.json()) as LogsPayload;
};

// ---- actions ----
export const replayQuery = (
  id: string,
  body: {
    query: string;
    mode: string;
    top_k: number;
    rerank?: boolean;
    // A18 — the logged filters, forwarded wholesale so a replay reproduces the
    // original query rather than a broader unfiltered one. Open shape: the
    // server logs whichever filters were set, and the /replay route spreads
    // whatever is present onto the QueryRequest.
    filters?: Record<string, unknown>;
  },
) => actData<ReplayResponse>(`/instances/${id}/queries/replay`, "POST", body);

export const clearCache = (id: string) =>
  actData(`/instances/${id}/cache`, "DELETE");
export const resetIndex = (id: string) =>
  actData(`/instances/${id}/index`, "DELETE");
export const addFolder = (id: string, body: object) =>
  actData(`/instances/${id}/index`, "POST", body);
export const removeFolder = (id: string, path: string) =>
  actData(`/instances/${id}/folders`, "DELETE", { folder_path: path });
export const cancelJob = (id: string, jobId: string) =>
  actData(`/instances/${id}/jobs/${jobId}`, "DELETE");
export const approveJob = (id: string, jobId: string) =>
  actData(`/instances/${id}/jobs/${jobId}/approve`, "POST");
export const gitReindex = (id: string) =>
  actData(`/instances/${id}/git/reindex`, "POST");
export const graphRebuild = (id: string) =>
  actData(`/instances/${id}/graph/rebuild`, "POST");
export const sessionsReindex = (id: string) =>
  actData(`/instances/${id}/sessions/reindex`, "POST");
export const memoryObsolete = (id: string, mid: string) =>
  actData(`/instances/${id}/memories/${mid}/obsolete`, "POST");
export const memoryDelete = (id: string, mid: string) =>
  actData(`/instances/${id}/memories/${mid}`, "DELETE");
export const memoryRebuild = (id: string) =>
  actData(`/instances/${id}/memories/rebuild`, "POST");
export const memoryCreate = (
  id: string,
  body: { text: string; section?: string; tags?: string[] },
) => actData(`/instances/${id}/memories`, "POST", body);

// ---------------------------------------------------------------------------
// Graph browse (Task 4 — sigma/graphology viz).
// Endpoints: GET /graph/nodes?q=&limit=  · GET /graph/neighbors?node=&limit=
// ---------------------------------------------------------------------------

const withDomains = (params: Record<string, string>, domains?: string[]) => {
  const p = new URLSearchParams(params);
  if (domains && domains.length > 0) p.set("domains", domains.join(","));
  return p;
};

export const searchGraphNodes = (id: string, q: string, limit = 20, domains?: string[]) =>
  getData<{ nodes: GraphNodeHit[] }>(
    `/instances/${id}/graph/nodes?${withDomains({ q, limit: String(limit) }, domains)}`,
  );

export const getGraphNeighbors = (id: string, node: string, limit = 200, domains?: string[]) =>
  getData<GraphSubgraph>(
    `/instances/${id}/graph/neighbors?${withDomains({ node, limit: String(limit) }, domains)}`,
  );

// Highest-degree hubs — seeds the browser with no search (GET /graph/top).
export const getGraphTopNodes = (id: string, limit = 20, domains?: string[]) =>
  getData<{ nodes: GraphNodeHit[] }>(
    `/instances/${id}/graph/top?${withDomains({ limit: String(limit) }, domains)}`,
  );

// Lazy source snippet for the node detail panel (GET /graph/node/source).
export const getGraphNodeSource = (id: string, node: string, context = 20) =>
  getData<GraphNodeSource>(
    `/instances/${id}/graph/node/source?${new URLSearchParams({
      node,
      context: String(context),
    })}`,
  );

// Impact analysis for the node detail panel (GET /graph/impact).
export const getGraphImpact = (id: string, node: string, maxDepth = 2, limit = 30) =>
  getData<{ node: string; nodes: GraphImpactNode[] }>(
    `/instances/${id}/graph/impact?${new URLSearchParams({
      node,
      max_depth: String(maxDepth),
      limit: String(limit),
    })}`,
  );

// Git co-change list for the node detail panel (GET /graph/cochange).
export const getGraphCochange = (id: string, node: string, minShared = 2, limit = 10) =>
  getData<{ node: string; files: GraphCochangeFile[] }>(
    `/instances/${id}/graph/cochange?${new URLSearchParams({
      node,
      min_shared: String(minShared),
      limit: String(limit),
    })}`,
  );

export const testProviders = (id: string) =>
  actData<ProviderTestResult>(`/instances/${id}/providers/test`, "POST");

// ---------------------------------------------------------------------------
// Usage telemetry (Plan 5 — GET /metrics/usage).
// ---------------------------------------------------------------------------

/** One row in `totals` — per-dimension window rollup. */
export type UsageTotalRow = {
  channel: string;
  provider: string;
  model: string;
  source: string;
  chunks: number;
  calls: number;
  triplets: number;
  tokens_in: number;
  tokens_out: number;
  cache_read: number;
  cache_write: number;
  errors: number;
};

/**
 * One row in `series` — per-time-bucket counts, tokens split by channel
 * (§6-F7). `bucket` is the slot-start in unix minutes (downsampled to
 * `bucket_size` minutes by the server per window).
 */
export type UsageSeriesRow = {
  bucket: number;
  chunks: number;
  calls: number;
  triplets: number;
  embed_tokens_in: number;
  embed_cache_read: number;
  llm_tokens_in: number;
  llm_tokens_out: number;
  llm_cache_read: number;
  llm_cache_write: number;
};

/** One row in `series_by_source` — token measures per time-bucket per source. */
export type UsageSourceSeriesRow = {
  bucket: number;
  channel: string;
  source: string;
  tokens_in: number;
  tokens_out: number;
  cache_read: number;
  cache_write: number;
};

/** One row in `queue` — latest gauge sample per source. */
export type UsageQueueRow = {
  source: string;
  depth: number;
  sampled_at: number; // unix timestamp
  active?: boolean; // false = the feature that drains this source is off
};

/** Full response from GET /metrics/usage. */
export type UsageMetrics = {
  window: string;
  now_bucket: number; // current minute bucket
  bucket_size: number; // series downsample size, in minutes
  totals: UsageTotalRow[];
  series: UsageSeriesRow[];
  series_by_source: UsageSourceSeriesRow[];
  queue: UsageQueueRow[];
};

/**
 * Fetch windowed usage telemetry for an instance.
 * A 503 (usage_metrics.enabled=false) surfaces as InstanceUnreachableError
 * with upstreamStatus=503 so the tab can show the disabled state.
 */
export async function getUsageMetrics(
  instanceId: string,
  window = "24h",
): Promise<UsageMetrics> {
  const r = await fetch(
    `${BASE}/instances/${instanceId}/metrics/usage?window=${window}`,
  );
  if (r.status === 502 || r.status === 503) {
    const body = (await readError(r)) as Record<string, unknown>;
    throw new InstanceUnreachableError(
      (body?.detail as string) ?? "usage metrics unavailable",
      r.status,
    );
  }
  if (!r.ok) {
    const body = (await readError(r)) as Record<string, unknown>;
    throw new Error((body?.detail as string) ?? r.statusText);
  }
  return (await r.json()) as UsageMetrics;
}
