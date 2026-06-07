import {
  Instance,
  UiSchema,
  InstanceStatusPayload,
  type ConfigValues,
  type EffectiveConfig,
  type FoldersPayload,
  type JobsPayload,
  type JobDetail,
  type CachePayload,
  type MemoriesPayload,
  type QueryRow,
  type QueryDetail,
  type ReplayResponse,
  type LogsPayload,
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
): Promise<{ ok: boolean; restarted: boolean }> {
  const r = await fetch(`${BASE}/instances/${id}/config`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ values, restart }),
  });
  if (!r.ok) {
    // 422 -> { errors: [...] }
    throw await readError(r);
  }
  return r.json();
}

// ---------------------------------------------------------------------------
// Global config — the machine-wide XDG config.yaml (every project inherits).
// This IS the global layer, so there is no effective/provenance resolution.
// ---------------------------------------------------------------------------

export const getGlobalConfig = () =>
  get("/global-config", (j) => j as ConfigValues);

export async function patchGlobalConfig(
  values: ConfigValues,
): Promise<{ ok: boolean }> {
  const r = await fetch(`${BASE}/global-config`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ values, restart: false }),
  });
  if (!r.ok) throw await readError(r); // 422 -> { errors: [...] }
  return r.json();
}

// ---------------------------------------------------------------------------
// Per-project runtime bind — config.json (bind_host / port range / auto_port).
// Read by the CLI at server start; changes need a RESTART to take effect.
// ---------------------------------------------------------------------------

export type RuntimeConfig = {
  bind_host: string;
  port_range_start: number;
  port_range_end: number;
  auto_port: boolean;
};

export const getRuntimeConfig = (id: string) =>
  get(`/instances/${id}/runtime-config`, (j) => j as RuntimeConfig);

export async function patchRuntimeConfig(
  id: string,
  values: Partial<RuntimeConfig>,
  restart: boolean,
): Promise<{ ok: boolean; restarted: boolean; restart_required: boolean }> {
  const r = await fetch(`${BASE}/instances/${id}/runtime-config`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ values, restart }),
  });
  if (!r.ok) throw await readError(r); // 422 -> { errors: [...] }
  return r.json();
}

// ---------------------------------------------------------------------------
// Control-plane ("server") settings — the dashboard's own config, distinct from
// per-instance config. (`dashboard:` block in the XDG config.yaml.)
// ---------------------------------------------------------------------------

export type DashboardSettings = {
  host: string;
  port: number;
  poll_s: number;
  autostart: boolean;
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

export async function patchSettings(values: {
  host?: string;
  port?: number;
  poll_s?: number;
  token?: string;
  autostart?: boolean;
}): Promise<{ ok: boolean; restart_required: string[] }> {
  const r = await fetch(`${BASE}/settings`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(values),
  });
  if (!r.ok) throw await readError(r); // 422 -> { errors: [...] }
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
export const getJobs = (id: string) =>
  getData<JobsPayload>(`/instances/${id}/jobs`);
export const getJobDetail = (id: string, jobId: string) =>
  getData<JobDetail>(`/instances/${id}/jobs/${jobId}`);
export const getCache = (id: string) =>
  getData<CachePayload>(`/instances/${id}/cache`);
export const getMemories = (id: string) =>
  getData<MemoriesPayload>(`/instances/${id}/memories`);

export function getQueries(
  id: string,
  q: { mode?: string; contains?: string; since?: number; limit?: number } = {},
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
  body: { query: string; mode: string; top_k: number },
) => actData<ReplayResponse>(`/instances/${id}/queries/replay`, "POST", body);

export const clearCache = (id: string) =>
  actData(`/instances/${id}/cache`, "DELETE");
export const resetIndex = (id: string) =>
  actData(`/instances/${id}/index`, "DELETE");
export const addFolder = (id: string, body: object) =>
  actData(`/instances/${id}/index`, "POST", body);
export const removeFolder = (id: string, path: string) =>
  actData(`/instances/${id}/folders`, "DELETE", { path });
export const cancelJob = (id: string, jobId: string) =>
  actData(`/instances/${id}/jobs/${jobId}`, "DELETE");
export const gitReindex = (id: string) =>
  actData(`/instances/${id}/git/reindex`, "POST");
export const sessionsReindex = (id: string) =>
  actData(`/instances/${id}/sessions/reindex`, "POST");
export const memoryObsolete = (id: string, mid: string) =>
  actData(`/instances/${id}/memories/${mid}/obsolete`, "POST");
export const memoryDelete = (id: string, mid: string) =>
  actData(`/instances/${id}/memories/${mid}`, "DELETE");
export const memoryRebuild = (id: string) =>
  actData(`/instances/${id}/memories/rebuild`, "POST");
