import { z } from "zod";

/** A managed project-server instance (running or known-but-stopped). */
export const Instance = z.object({
  id: z.string(),
  name: z.string(),
  project_root: z.string(),
  state_dir: z.string().optional().default(""),
  base_url: z.string(),
  pid: z.number().nullable().default(null),
  mode: z.string(),
  status: z.enum(["running", "unhealthy", "stopped", "stale"]),
  started_at: z.string().optional().default(""),
});
export type Instance = z.infer<typeof Instance>;
export type InstanceStatus = Instance["status"];

/** One control in the data-driven config form. Recursive via `fields`. */
export type SchemaField = {
  key: string;
  dotpath: string;
  label: string;
  widget: "enum" | "toggle" | "int" | "text" | "group" | "dict" | "stringlist";
  secret?: boolean;
  options?: string[];
  presets?: string[];
  placeholder?: string;
  min?: number;
  max?: number;
  step?: number;
  help?: string;
  /** Effective default when the project config omits this field (may be null). */
  default?: unknown;
  visible_when?: { field: string; equals: string };
  fields?: SchemaField[];
};

export const SchemaField: z.ZodType<SchemaField> = z.lazy(() =>
  z.object({
    key: z.string(),
    dotpath: z.string(),
    label: z.string(),
    widget: z.enum([
      "enum",
      "toggle",
      "int",
      "text",
      "group",
      "dict",
      "stringlist",
    ]),
    secret: z.boolean().optional(),
    options: z.array(z.string()).optional(),
    presets: z.array(z.string()).optional(),
    placeholder: z.string().optional(),
    min: z.number().optional(),
    max: z.number().optional(),
    step: z.number().optional(),
    help: z.string().optional(),
    default: z.unknown().optional(),
    visible_when: z.object({ field: z.string(), equals: z.string() }).optional(),
    fields: z.array(SchemaField).optional(),
  }),
);

export const UiSchemaSection = z.object({
  key: z.string(),
  label: z.string(),
  description: z.string().optional(),
  fields: z.array(SchemaField),
});
export type UiSchemaSection = z.infer<typeof UiSchemaSection>;

/** Canonical provider descriptor (kind -> provider -> info). Drives the
 *  conditional rendering of the embedding/summarization/reranker sections. */
export const ProviderInfo = z.object({
  models: z.array(z.string()),
  needs_base_url: z.boolean(),
  default_api_key_env: z.string().nullable(),
});
export type ProviderInfo = z.infer<typeof ProviderInfo>;

/** kind ("embedding"|"summarization"|"reranker") -> provider name -> info. */
export const ProvidersDescriptor = z.record(
  z.string(),
  z.record(z.string(), ProviderInfo),
);
export type ProvidersDescriptor = z.infer<typeof ProvidersDescriptor>;

export const UiSchema = z.object({
  sections: z.array(UiSchemaSection),
  providers: ProvidersDescriptor.optional(),
});
export type UiSchema = z.infer<typeof UiSchema>;

/** Arbitrary nested config dict; secrets come back as "********". */
export type ConfigValues = Record<string, unknown>;

/** Per-key effective value + provenance across project > global > code default. */
export type EffectiveSource = "project" | "global" | "default" | "unset";
export type EffectiveEntry = {
  value: unknown;
  source: EffectiveSource;
  /**
   * For a PROJECT-sourced key: the value+source it would fall back to if the
   * project override were removed (unset) — global, else code default, else
   * null. Powers the "if you unset, you'll use X from <source>" hint. Absent /
   * null for keys not set at the project layer.
   */
  inherited?: { value: unknown; source: EffectiveSource } | null;
};
export type EffectiveConfig = Record<string, EffectiveEntry>;

/** Response of POST /config/unset. */
export type UnsetResult = {
  removed: string[];
  effective: Record<string, { value: unknown; source: EffectiveSource }>;
};

/** Validation error returned by a 422 PATCH. */
export type ConfigError = { field: string; message: string; suggestion?: string };
export type ConfigErrorEnvelope = { errors: ConfigError[] };

/** Data-incompatibility conflict returned by a 409 PATCH (save guard). */
export type DataConflictEnvelope = {
  conflict: "data_incompatible";
  message: string;
  fields: { dotpath: string; current: unknown; new: unknown }[];
  counts: { documents: number | null; chunks: number | null };
};

/** Per-instance status payload (best-effort; tolerant of partial servers). */
export const InstanceStatusPayload = z
  .object({
    total_documents: z.number().optional(),
    total_chunks: z.number().optional(),
    total_code_chunks: z.number().optional(),
    total_doc_chunks: z.number().optional(),
    code_documents: z.number().optional(),
    doc_documents: z.number().optional(),
    // The server returns the LIST of indexed folders (paths/objects), not a
    // count. Accept either form so a partial/older server can't break parsing.
    indexed_folders: z.union([z.number(), z.array(z.unknown())]).optional(),
    supported_languages: z.array(z.unknown()).optional(),
    indexing_in_progress: z.boolean().optional(),
    current_job_id: z.string().nullable().optional(),
    progress_percent: z.number().nullable().optional(),
    last_indexed_at: z.string().nullable().optional(),
    queue_pending: z.number().optional(),
    queue_running: z.number().optional(),
    graph_index: z.unknown().optional(),
    embedding_cache: z.unknown().optional(),
    query_cache: z.unknown().optional(),
    file_watcher: z.unknown().optional(),
    session_chunks: z.number().optional(),
    git_commits: z.number().optional(),
    features: z.unknown().optional(),
  })
  .passthrough();
export type InstanceStatusPayload = z.infer<typeof InstanceStatusPayload>;

// ---------------------------------------------------------------------------
// Per-instance data shapes (Phase 06). Field names confirmed against the live
// server JSON (see plan 06 "REAL payload shapes"):
//   folders -> /index/folders/  ·  jobs -> /index/jobs/  ·  cache -> /index/cache/
//   memories -> /memories/  ·  queries -> /query/history[...]  ·  logs -> /health/logs
// ---------------------------------------------------------------------------

/** One indexed folder row (server `/index/folders/`). */
export type FolderRow = {
  folder_path: string;
  chunk_count: number;
  last_indexed: string | null;
  watch_mode: string; // "auto" | "off"
  watch_debounce_seconds: number | null;
};
export type FoldersPayload = { folders: FolderRow[]; total: number };

/** Indexed-file listing for one folder (server `/index/documents`). */
export type DocumentRow = {
  path: string;
  chunk_count: number;
  size_bytes: number;
  mtime: number;
  last_embedded_at: number;
};
export type DocumentsPayload = {
  folder: string;
  total: number;
  files: DocumentRow[];
};

/** Chunks of one file (server `/index/documents/chunks`). */
export type ChunkRow = {
  chunk_id: string;
  text: string;
  metadata: Record<string, unknown>;
};
export type DocumentChunksPayload = {
  path: string;
  total_chunks: number;
  chunks: ChunkRow[];
};

/** One indexing job (server `/index/jobs/`). */
export type JobRow = {
  id: string;
  status: string; // queued | running | done | error | cancelled
  folder_path: string;
  operation: string;
  include_code: boolean;
  source: string;
  enqueued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  progress_percent: number | null;
  chunks_added: number;
  chunks_removed: number;
  error: string | null;
};
export type JobsPayload = { jobs: JobRow[] };

/** Per-job progress counters (server `JobProgress`). */
export type JobProgress = {
  files_processed: number;
  files_total: number;
  chunks_created: number;
  current_file: string;
  percent: number;
  percent_complete: number;
};

/** Full job detail (server `/index/jobs/{job_id}`) — "what the job did". */
export type JobDetail = {
  id: string;
  status: string;
  folder_path: string;
  operation: string;
  include_code: boolean;
  source: string;
  enqueued_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  execution_time_ms: number | null;
  progress: JobProgress | null;
  progress_percent: number;
  total_documents: number;
  total_chunks: number;
  chunks_added: number;
  chunks_removed: number;
  error: string | null;
  retry_count: number;
  cancel_requested: boolean;
  eviction_summary: Record<string, number> | null;
};

/** Embedding-cache stats (server `/index/cache/`). */
export type CachePayload = {
  hits: number;
  misses: number;
  hit_rate: number;
  mem_entries: number;
  entry_count: number;
  size_bytes: number;
};

/** Cache hit-rate snapshot history (server `/index/cache/history`). */
export type CacheSnapshot = {
  ts: number;
  hits: number;
  misses: number;
  entry_count: number;
  size_bytes: number;
};
export type CacheHistoryPayload = { snapshots: CacheSnapshot[] };

/** Cost estimate (server `/index/cache/economics`). All `est_*` may be null. */
export type CacheEconomics = {
  provider: string;
  model: string;
  price_usd_per_mtok: number | null;
  avg_tokens_per_chunk: number;
  session_hits: number;
  session_misses: number;
  est_spend_usd: number | null;
  est_saved_usd: number | null;
  cached_entries: number;
  est_reindex_cost_usd: number | null;
};

/** Curated session memory (server `/memories/`). */
export type MemoryRow = {
  id: string;
  content?: string;
  category?: string;
  created_at?: string;
  obsolete?: boolean;
  [k: string]: unknown;
};
export type MemoriesPayload = {
  memories: MemoryRow[];
  total: number;
  char_count: number;
  char_cap: number;
};

/** Archived-session metadata (server `/sessions/archive`). */
export type ArchivedSession = {
  session_id: string;
  /** First line of the first user prompt, for display; null when unavailable. */
  title: string | null;
  archive_path: string;
  mtime: number;
  size_bytes: number;
};
export type SessionArchivePayload = {
  sessions: ArchivedSession[];
  archived_sessions: number;
  archived_files: number;
  tombstoned: number;
  archived_bytes: number;
};

/** Decision browse + temporal timeline (server `/sessions/{decisions,timeline}`). */
export type DecisionNode = { id: string; name: string; label: string };
export type TimelineRow = {
  subject: string;
  predicate: string;
  object: string;
  valid_from: string | null;
  valid_until: string | null;
  valid: boolean;
};

/** Query-history list row (server `/query/history`). */
export type QueryRow = {
  id: string;
  ts: number; // epoch float seconds
  mode: string;
  query: string;
  top_k: number;
  latency_ms: number;
  result_count: number;
  alpha: number | null;
};

/** A single ranked result inside a query-history detail. */
export type QueryResultRow = {
  score: number | null;
  path: string | null;
  lines: [number, number] | null;
  snippet: string;
};

/** Query-history detail (server `/query/history/{qid}`). */
export type QueryDetail = QueryRow & {
  filters: { source_types?: string[] | null; languages?: string[] | null };
  results: QueryResultRow[];
};

/** Aggregated query analytics (server `/query/stats`). */
export type QueryStats = {
  total: number;
  zero_result_count: number;
  mode_distribution: Record<string, number>;
  latency: { p50: number; p95: number; avg: number };
  latency_trend: Array<{ bucket: string; count: number; p50: number; p95: number }>;
  top_queries: Array<{
    query: string;
    count: number;
    avg_latency_ms: number;
    zero_results: number;
    last_ts: number;
    /** Id of the most recent occurrence — opens that query's detail drawer. */
    last_id: string;
  }>;
  zero_result_queries: Array<{ query: string; count: number; last_ts: number }>;
};

/** Live replay response (server `/query/`). */
export type ReplayResult = {
  text: string;
  source: string;
  score: number;
  chunk_id: string;
  source_type?: string;
  language?: string | null;
  vector_score?: number | null;
  bm25_score?: number | null;
  graph_score?: number | null;
  rerank_score?: number | null;
  original_rank?: number | null;
  [k: string]: unknown;
};
export type ReplayResponse = {
  results: ReplayResult[];
  query_time_ms: number;
  total_results: number;
};

/** Server log tail (server `/health/logs`). */
export type LogsPayload = { lines: string[]; unavailable?: boolean };

/** Graph browse (server `/graph/nodes`, `/graph/neighbors`). */
export type GraphNodeHit = {
  id: string;
  name: string;
  label: string | null;
  degree: number;
};
export type GraphSubgraph = {
  nodes: Array<{ id: string; name: string; label: string | null }>;
  edges: Array<{ id: string; source: string; target: string; label: string | null }>;
};

/** Live provider connectivity test (server `POST /health/providers/test`). */
export type ProviderTestResult = {
  embedding: {
    provider: string;
    model: string;
    ok: boolean;
    latency_ms: number;
    error: string | null;
  };
  summarization: {
    provider: string;
    model: string;
    ok: boolean;
    checked: string;
    error: string | null;
  };
};
