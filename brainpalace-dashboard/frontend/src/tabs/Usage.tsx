import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart2, Clock, Layers, AlertTriangle, Info } from "lucide-react";
import { getUsageMetrics, InstanceUnreachableError } from "../api/client";
import type {
  UsageTotalRow,
  UsageSeriesRow,
  UsageSourceSeriesRow,
  UsageQueueRow,
} from "../api/client";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
} from "recharts";
import { useOptionalSelectedInstance } from "../state/selectedInstance";
import { NoInstance, TabSkeleton } from "../components/TabState";

// ---- helpers ----------------------------------------------------------------

const fmt = (n: number) => n.toLocaleString("en-US");

const WINDOWS = ["1h", "24h", "7d", "30d"] as const;
type Window = (typeof WINDOWS)[number];

const TOOLTIP_STYLE = {
  background: "#0b1118",
  border: "1px solid #1e2c3a",
  borderRadius: 10,
  color: "#e6edf3",
  fontSize: 12,
} as const;

/**
 * Format a minute bucket (unixtime / 60) as a local label. Short windows show
 * clock time (HH:MM); multi-day windows add the date so bars stay legible.
 */
const bucketLabel = (bucket: number, bucketSize: number) => {
  const d = new Date(bucket * 60_000);
  if (bucketSize >= 360) {
    // 6h+ slots (30d window) — date + hour, 24h clock
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      hour12: false,
    });
  }
  if (bucketSize >= 60) {
    // hourly slots (7d window) — weekday + hour, 24h clock
    return d.toLocaleString(undefined, {
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  }
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
};

/** Tooltip that always shows the bar value + unit above the time label. */
function ChartTooltip({
  active,
  payload,
  label,
  unit,
}: {
  active?: boolean;
  payload?: { value?: number | string | (number | string)[] }[];
  label?: string | number;
  unit: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const raw = payload[0]?.value;
  const value = typeof raw === "number" ? raw : Number(raw) || 0;
  return (
    <div style={TOOLTIP_STYLE} className="px-2.5 py-1.5">
      <div className="font-semibold tabular-nums text-fg">
        {fmt(value)} {unit}
      </div>
      <div className="text-fg-faint">{label}</div>
    </div>
  );
}

/** Seconds elapsed since a unix timestamp, formatted as "Xm ago" / "Xs ago". */
function agoLabel(sampled_at: number): string {
  const diffS = Math.max(0, Math.floor(Date.now() / 1000) - sampled_at);
  if (diffS < 60) return `${diffS}s ago`;
  return `${Math.floor(diffS / 60)}m ago`;
}

/** True when the sampled_at is older than 10 minutes — reconciler may be idle. */
function isStale(sampled_at: number): boolean {
  return Date.now() / 1000 - sampled_at > 600;
}

// Plain-language names for the raw channel / source identifiers.
const CHANNEL_LABEL: Record<string, string> = {
  provider: "Language model",
  embedding: "Embeddings (search)",
  subagent: "Graph extraction",
  "code-ast": "Code parsing",
};
const CHANNEL_HINT: Record<string, string> = {
  provider: "LLM that writes summaries and extracts facts (e.g. Anthropic).",
  embedding: "Turns your text into search vectors (OpenAI).",
  subagent: "Knowledge-graph extraction — free, runs in your AI client.",
  "code-ast": "Code structure parsing — free, runs locally.",
};
const SOURCE_LABEL: Record<string, string> = {
  doc: "Documents",
  code: "Code",
  session: "Sessions",
  git: "Git history",
  query: "Search queries",
  unknown: "Other",
};
const channelLabel = (c: string) => CHANNEL_LABEL[c] ?? c;
const sourceLabel = (s: string) => SOURCE_LABEL[s] ?? s;
// Which feature drains each backlog source — shown when that feature is off.
const queueOffNote = (s: string) =>
  s === "session" ? "summarization off" : "extraction off";

const sumRows = (rows: UsageTotalRow[], key: keyof UsageTotalRow) =>
  rows.reduce((acc, r) => acc + (r[key] as number), 0);

// ---- sub-components ---------------------------------------------------------

function SectionHeader({
  icon,
  title,
  subtitle,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
}) {
  return (
    <div className="mb-4 flex items-center gap-2">
      <span className="text-accent" aria-hidden="true">
        {icon}
      </span>
      <div>
        <h2 className="font-display text-base font-semibold tracking-tight">
          {title}
        </h2>
        {subtitle && <p className="text-xs text-fg-faint">{subtitle}</p>}
      </div>
    </div>
  );
}

function WindowSelector({
  value,
  onChange,
}: {
  value: Window;
  onChange: (w: Window) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Time window"
      className="inline-flex rounded-lg border border-line/60 bg-ink-800 p-0.5 text-xs font-medium"
    >
      {WINDOWS.map((w) => (
        <button
          key={w}
          type="button"
          onClick={() => onChange(w)}
          className={`rounded-md px-3 py-1.5 transition-colors ${
            value === w
              ? "bg-accent/20 text-accent"
              : "text-fg-muted hover:text-fg"
          }`}
        >
          {w}
        </button>
      ))}
    </div>
  );
}

// ---- one trend chart per value ----------------------------------------------

type ChartRow = UsageSeriesRow & { label: string; partial: boolean };

function MetricChart({
  title,
  hint,
  total,
  unit,
  testId,
  data,
  dataKey,
  color,
}: {
  title: string;
  hint: string;
  total: number;
  unit: string;
  testId: string;
  data: ChartRow[];
  dataKey: keyof UsageSeriesRow;
  color: string;
}) {
  return (
    <div className="panel p-5">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <p
          className="cursor-help text-sm font-semibold text-fg-muted decoration-dotted underline-offset-2 hover:underline"
          title={hint}
        >
          {title}
        </p>
        <span
          data-testid={testId}
          className="font-display text-lg font-semibold tabular-nums tracking-tight text-fg"
        >
          {fmt(total)}
        </span>
      </div>
      <p className="mb-3 text-[11px] text-fg-faint">
        {unit} in window · per-hour below
      </p>
      <div style={{ width: "100%", height: 130 }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 4, right: 8, bottom: 2, left: 0 }}>
            <XAxis
              dataKey="label"
              tick={{ fill: "#5f7488", fontSize: 9 }}
              axisLine={{ stroke: "#1e2c3a" }}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              allowDecimals={false}
              tick={{ fill: "#5f7488", fontSize: 9 }}
              axisLine={false}
              tickLine={false}
              width={34}
            />
            <Tooltip
              cursor={{ fill: "rgba(148,163,184,0.06)" }}
              content={(p) => <ChartTooltip {...p} unit={unit} />}
            />
            <Bar dataKey={dataKey} radius={[3, 3, 0, 0]} barSize={12}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.partial ? `${color}44` : color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// ---- per-source charts ------------------------------------------------------

type SourcePoint = { label: string; value: number; partial: boolean };

/** Like MetricChart but for a prebuilt single-series dataset (per source). */
function SourceChart({
  title,
  total,
  unit,
  color,
  data,
}: {
  title: string;
  total: number;
  unit: string;
  color: string;
  data: SourcePoint[];
}) {
  return (
    <div className="panel p-5">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <p className="text-sm font-semibold text-fg-muted">{title}</p>
        <span className="font-display text-lg font-semibold tabular-nums tracking-tight text-fg">
          {fmt(total)}
        </span>
      </div>
      <p className="mb-3 text-[11px] text-fg-faint">{unit} in window</p>
      <div style={{ width: "100%", height: 130 }}>
        <ResponsiveContainer>
          <BarChart data={data} margin={{ top: 4, right: 8, bottom: 2, left: 0 }}>
            <XAxis
              dataKey="label"
              tick={{ fill: "#5f7488", fontSize: 9 }}
              axisLine={{ stroke: "#1e2c3a" }}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              allowDecimals={false}
              tick={{ fill: "#5f7488", fontSize: 9 }}
              axisLine={false}
              tickLine={false}
              width={34}
            />
            <Tooltip
              cursor={{ fill: "rgba(148,163,184,0.06)" }}
              content={(p) => <ChartTooltip {...p} unit={unit} />}
            />
            <Bar dataKey="value" radius={[3, 3, 0, 0]} barSize={12}>
              {data.map((d, i) => (
                <Cell key={i} fill={d.partial ? `${color}44` : color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/** Build one per-source dataset for a token measure within a channel. */
function bySourceCharts(
  rows: UsageSourceSeriesRow[],
  channel: string,
  measure: "tokens_in" | "tokens_out",
  nowBucket: number,
  bucketSize: number,
  alwaysSources: string[] = [],
): { source: string; total: number; data: SourcePoint[] }[] {
  const currentSlot = nowBucket - (nowBucket % bucketSize);
  const bySource = new Map<string, SourcePoint[]>();
  const totals = new Map<string, number>();
  // Seed the canonical sources so they render even with zero activity.
  for (const s of alwaysSources) {
    bySource.set(s, []);
    totals.set(s, 0);
  }
  for (const r of rows) {
    if (r.channel !== channel) continue;
    const v = r[measure];
    const pts = bySource.get(r.source) ?? [];
    pts.push({
      label: bucketLabel(r.bucket, bucketSize),
      value: v,
      partial: r.bucket >= currentSlot,
    });
    bySource.set(r.source, pts);
    totals.set(r.source, (totals.get(r.source) ?? 0) + v);
  }
  return [...bySource.entries()]
    .map(([source, data]) => ({ source, total: totals.get(source) ?? 0, data }))
    .sort((a, b) => b.total - a.total);
}

// ---- the grid of per-value charts -------------------------------------------

function MetricGrid({
  totals,
  series,
  bySource,
  nowBucket,
  bucketSize,
}: {
  totals: UsageTotalRow[];
  series: UsageSeriesRow[];
  bySource: UsageSourceSeriesRow[];
  nowBucket: number;
  bucketSize: number;
}) {
  if (series.length === 0) return null;

  // The slot containing "now" is still filling — dim it.
  const currentSlot = nowBucket - (nowBucket % bucketSize);
  const data: ChartRow[] = series.map((s) => ({
    ...s,
    label: bucketLabel(s.bucket, bucketSize),
    partial: s.bucket >= currentSlot,
  }));

  const llm = totals.filter((r) => r.channel === "provider");
  const emb = totals.filter((r) => r.channel === "embedding");
  const llmActive = sumRows(llm, "tokens_in") + sumRows(llm, "calls") > 0;

  // Canonical sources so the by-source grids always show the same charts,
  // even when a source had no activity this window.
  const EMBED_SOURCES = ["doc", "code", "git", "session"];
  const LLM_SOURCES = ["session", "doc"];
  const embBySource = bySourceCharts(
    bySource,
    "embedding",
    "tokens_in",
    nowBucket,
    bucketSize,
    EMBED_SOURCES,
  );
  const llmSentBySource = bySourceCharts(
    bySource,
    "provider",
    "tokens_in",
    nowBucket,
    bucketSize,
    LLM_SOURCES,
  );
  const llmRecvBySource = bySourceCharts(
    bySource,
    "provider",
    "tokens_out",
    nowBucket,
    bucketSize,
    LLM_SOURCES,
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Embeddings & indexing */}
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-fg-muted">
          Embeddings &amp; indexing
        </p>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricChart
            title="Embedding tokens sent →"
            hint="Tokens of your text sent to OpenAI to build the search index. Sent only — an embedding returns a vector, not text, so nothing comes back."
            total={sumRows(emb, "tokens_in")}
            unit="tokens"
            testId="usage-embed-tokens-in"
            data={data}
            dataKey="embed_tokens_in"
            color="#a78bfa"
          />
          <MetricChart
            title="Chunks embedded"
            hint="Pieces of text (one chunk ≈ a function or a paragraph) turned into vectors."
            total={sumRows(emb, "chunks")}
            unit="chunks"
            testId="usage-chunks"
            data={data}
            dataKey="chunks"
            color="#2dd4bf"
          />
          <MetricChart
            title="API requests"
            hint="Calls made to the embedding / language-model APIs (texts are batched per call)."
            total={sumRows(totals, "calls")}
            unit="requests"
            testId="usage-calls"
            data={data}
            dataKey="calls"
            color="#38bdf8"
          />
          <MetricChart
            title="Knowledge-graph facts"
            hint="Relationship facts (subject → relation → object) extracted from code and docs. Free — no API tokens."
            total={sumRows(totals, "triplets")}
            unit="facts"
            testId="usage-triplets"
            data={data}
            dataKey="triplets"
            color="#f59e0b"
          />
        </div>
      </div>

      {/* Embedding tokens sent — split per data source */}
      {embBySource.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-fg-muted">
            Embedding tokens sent — by source
          </p>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {embBySource.map((c) => (
              <SourceChart
                key={c.source}
                title={sourceLabel(c.source)}
                total={c.total}
                unit="tokens"
                color="#a78bfa"
                data={c.data}
              />
            ))}
          </div>
        </div>
      )}

      {/* Language model */}
      <div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-fg-muted">
          Language model — text generation
          {!llmActive && (
            <span className="ml-2 font-normal normal-case text-fg-faint">
              (idle this window — no summarizing ran)
            </span>
          )}
        </p>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricChart
            title="Tokens sent →"
            hint="Prompt tokens sent to the model."
            total={sumRows(llm, "tokens_in")}
            unit="tokens"
            testId="usage-llm-tokens-in"
            data={data}
            dataKey="llm_tokens_in"
            color="#2dd4bf"
          />
          <MetricChart
            title="← Tokens received"
            hint="Tokens the model generated back (its reply)."
            total={sumRows(llm, "tokens_out")}
            unit="tokens"
            testId="usage-llm-tokens-out"
            data={data}
            dataKey="llm_tokens_out"
            color="#38bdf8"
          />
          <MetricChart
            title="Cache read"
            hint="Prompt tokens served from the provider's cache instead of re-sending (cheaper)."
            total={sumRows(llm, "cache_read")}
            unit="tokens"
            testId="usage-cache-read"
            data={data}
            dataKey="llm_cache_read"
            color="#34d399"
          />
          <MetricChart
            title="Cache write"
            hint="Prompt tokens written to the provider's cache for later reuse."
            total={sumRows(llm, "cache_write")}
            unit="tokens"
            testId="usage-cache-write"
            data={data}
            dataKey="llm_cache_write"
            color="#f472b6"
          />
        </div>
      </div>

      {/* LLM tokens sent — split per data source */}
      {llmActive && llmSentBySource.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-fg-muted">
            LLM tokens sent — by source
          </p>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {llmSentBySource.map((c) => (
              <SourceChart
                key={c.source}
                title={sourceLabel(c.source)}
                total={c.total}
                unit="tokens"
                color="#2dd4bf"
                data={c.data}
              />
            ))}
          </div>
        </div>
      )}

      {/* LLM tokens received — split per data source */}
      {llmActive && llmRecvBySource.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-fg-muted">
            LLM tokens received — by source
          </p>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {llmRecvBySource.map((c) => (
              <SourceChart
                key={c.source}
                title={sourceLabel(c.source)}
                total={c.total}
                unit="tokens"
                color="#38bdf8"
                data={c.data}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---- queue widget ------------------------------------------------------------

function QueueWidget({ queue }: { queue: UsageQueueRow[] }) {
  if (queue.length === 0) return null;
  return (
    <div className="panel p-6">
      <SectionHeader
        icon={<Layers className="h-4 w-4" />}
        title="Queue backlog"
        subtitle="Pending work waiting to be processed (current depth, not a trend)"
      />
      <div className="flex flex-wrap gap-6">
        {queue.map((q) => {
          const stale = isStale(q.sampled_at);
          return (
            <div key={q.source} className="flex flex-col gap-1">
              <span className="eyebrow">{sourceLabel(q.source)}</span>
              <span
                data-testid={`usage-queue-${q.source}`}
                className="font-display text-2xl font-semibold tabular-nums tracking-tight text-fg"
              >
                {fmt(q.depth)}
              </span>
              <span
                className={`flex items-center gap-1 text-xs ${
                  stale ? "text-warn" : "text-fg-faint"
                }`}
              >
                <Clock className="h-3 w-3" aria-hidden="true" />
                as of {agoLabel(q.sampled_at)}
                {stale && (
                  <span className="ml-1 text-warn">(reconciler may be idle)</span>
                )}
              </span>
              {q.active === false && (
                <span
                  data-testid={`usage-queue-${q.source}-off`}
                  className="text-xs text-warn"
                >
                  {queueOffNote(q.source)} — not draining
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---- breakdown tables (the detail: where each number came from) -------------

const FREE_CHANNELS = new Set(["subagent", "code-ast"]);
const LOCAL_PROVIDERS = new Set(["ollama"]);

function TokenCell({ row }: { row: UsageTotalRow }) {
  if (FREE_CHANNELS.has(row.channel)) {
    return (
      <span className="text-fg-faint" title="Free / CC-side — not metered server-side">
        —
      </span>
    );
  }
  if (LOCAL_PROVIDERS.has(row.provider) && row.tokens_in === 0) {
    return <span className="text-fg-faint">0 (no usage reported)</span>;
  }
  return <>{fmt(row.tokens_in)}</>;
}

function BreakdownTables({ totals }: { totals: UsageTotalRow[] }) {
  if (totals.length === 0) return null;

  const byChannel = new Map<string, UsageTotalRow[]>();
  for (const row of totals) {
    const group = byChannel.get(row.channel) ?? [];
    group.push(row);
    byChannel.set(row.channel, group);
  }

  const channelOrder = ["provider", "embedding", "subagent", "code-ast"];
  const channels = [
    ...channelOrder.filter((c) => byChannel.has(c)),
    ...[...byChannel.keys()].filter((c) => !channelOrder.includes(c)),
  ];

  return (
    <div className="panel p-6">
      <SectionHeader
        icon={<Info className="h-4 w-4" />}
        title="Where it came from"
        subtitle="The same numbers, grouped by channel → provider / model → source"
      />
      <div className="flex flex-col gap-8">
        {channels.map((channel) => {
          const rows = byChannel.get(channel)!;
          const isFree = FREE_CHANNELS.has(channel);
          return (
            <div key={channel}>
              <div className="mb-2 flex items-center gap-2">
                <span className="rounded bg-ink-700 px-2 py-0.5 text-xs font-semibold text-fg">
                  {channelLabel(channel)}
                </span>
                <span className="text-xs text-fg-faint">
                  {isFree
                    ? "free — not metered server-side"
                    : CHANNEL_HINT[channel]}
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-sm">
                  <thead>
                    <tr className="border-b border-line/60">
                      {!isFree && (
                        <th className="py-2 pr-4 text-left text-xs font-semibold text-fg-muted">
                          Provider / Model
                        </th>
                      )}
                      <th className="py-2 pr-4 text-left text-xs font-semibold text-fg-muted">
                        Source
                      </th>
                      <th className="py-2 pr-3 text-right text-xs font-semibold text-fg-muted">
                        Chunks
                      </th>
                      <th className="py-2 pr-3 text-right text-xs font-semibold text-fg-muted">
                        Requests
                      </th>
                      <th className="py-2 pr-3 text-right text-xs font-semibold text-fg-muted">
                        Graph facts
                      </th>
                      <th
                        className="py-2 pr-3 text-right text-xs font-semibold text-fg-muted"
                        title="Tokens sent to the provider"
                      >
                        Tokens sent →
                      </th>
                      <th
                        className="py-2 pr-3 text-right text-xs font-semibold text-fg-muted"
                        title="Tokens generated back (LLM only; embeddings have none)"
                      >
                        ← Received
                      </th>
                      <th className="py-2 pr-3 text-right text-xs font-semibold text-fg-muted">
                        Cache reused
                      </th>
                      <th className="py-2 pr-3 text-right text-xs font-semibold text-fg-muted">
                        Cache written
                      </th>
                      <th className="py-2 text-right text-xs font-semibold text-fg-muted">
                        Errors
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/40">
                    {rows.map((row, i) => (
                      <tr key={i} className="hover:bg-ink-700/30 transition-colors">
                        {!isFree && (
                          <td className="py-2 pr-4 font-mono text-xs text-fg">
                            {row.provider || "—"}
                            {row.model ? (
                              <span className="ml-1 text-fg-faint">
                                / {row.model}
                              </span>
                            ) : null}
                          </td>
                        )}
                        <td className="py-2 pr-4 text-xs text-fg-muted">
                          {sourceLabel(row.source)}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-xs">
                          {fmt(row.chunks)}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-xs">
                          {fmt(row.calls)}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-xs">
                          {fmt(row.triplets)}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-xs">
                          <TokenCell row={row} />
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-xs">
                          {isFree ? (
                            <span className="text-fg-faint">—</span>
                          ) : (
                            fmt(row.tokens_out)
                          )}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-xs">
                          {isFree ? (
                            <span className="text-fg-faint">—</span>
                          ) : (
                            fmt(row.cache_read)
                          )}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-xs">
                          {isFree ? (
                            <span className="text-fg-faint">—</span>
                          ) : (
                            fmt(row.cache_write)
                          )}
                        </td>
                        <td className="py-2 text-right tabular-nums text-xs">
                          {row.errors > 0 ? (
                            <span className="text-warn">{fmt(row.errors)}</span>
                          ) : (
                            <span className="text-fg-faint">0</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---- main tab ---------------------------------------------------------------

export function Usage({ instanceId }: { instanceId?: string }) {
  const ctx = useOptionalSelectedInstance();
  const id = instanceId ?? ctx?.selectedId ?? null;
  const [window, setWindow] = useState<Window>("1h");

  const usageQ = useQuery({
    queryKey: ["usage", id, window],
    queryFn: () => getUsageMetrics(id!, window),
    enabled: !!id,
    retry: false,
    refetchInterval: 30_000,
  });

  if (!id) {
    return (
      <NoInstance
        testId="tab-usage"
        message="Select an instance to see its usage telemetry."
      />
    );
  }

  if (usageQ.isLoading) {
    return (
      <div data-testid="tab-usage">
        <TabSkeleton rows={3} />
      </div>
    );
  }

  if (!usageQ.data) {
    // 503 = usage_metrics.enabled=false; 502 = instance unreachable.
    if (usageQ.error instanceof InstanceUnreachableError) {
      const is503 = usageQ.error.upstreamStatus === 503;
      return (
        <div
          data-testid="usage-disabled"
          className="panel grid place-items-center p-12"
        >
          <div className="text-center">
            <BarChart2
              className="mx-auto mb-3 h-6 w-6 text-fg-faint"
              aria-hidden="true"
            />
            <p className="text-sm font-semibold text-fg-muted">
              {is503
                ? "Usage metrics are off."
                : "Instance is stopped or unreachable."}
            </p>
            <p className="mt-1 text-xs text-fg-faint">
              {is503 ? (
                <>
                  Enable with{" "}
                  <code className="rounded bg-ink-900/40 px-1 py-0.5 font-mono">
                    usage_metrics.enabled: true
                  </code>{" "}
                  in your project config.
                </>
              ) : (
                "Start the instance from the Instances tab to see usage data."
              )}
            </p>
          </div>
        </div>
      );
    }
    return (
      <div data-testid="tab-usage">
        <TabSkeleton rows={1} />
      </div>
    );
  }

  const { totals, series, series_by_source, queue, now_bucket, bucket_size } =
    usageQ.data;
  const hasData = totals.length > 0 || series.length > 0 || queue.length > 0;
  const errors = sumRows(totals, "errors");

  if (!hasData) {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between">
          <h1 className="font-display text-lg font-semibold tracking-tight">
            Usage
          </h1>
          <WindowSelector value={window} onChange={setWindow} />
        </div>
        <div
          data-testid="usage-empty"
          className="panel grid place-items-center p-12"
        >
          <div className="text-center">
            <BarChart2
              className="mx-auto mb-3 h-6 w-6 text-fg-faint"
              aria-hidden="true"
            />
            <p className="text-sm text-fg-muted">
              No usage recorded in this window.
            </p>
            <p className="mt-1 text-xs text-fg-faint">
              Charts appear here once indexing, querying, or extraction runs.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="tab-usage" className="flex flex-col gap-4">
      {/* header + window selector */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-lg font-semibold tracking-tight">
            Usage
          </h1>
          <p className="text-xs text-fg-faint">
            Each chart is one metric over time. The big number is the window
            total; bars are per-hour. The faint trailing bar is the current hour
            (still filling).
          </p>
        </div>
        <WindowSelector value={window} onChange={setWindow} />
      </div>

      {errors > 0 && (
        <div className="flex items-center gap-2 rounded-lg border border-warn/30 bg-warn/10 px-4 py-2.5">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-warn" aria-hidden="true" />
          <span className="text-sm text-warn" data-testid="usage-errors">
            {fmt(errors)} failed request{errors !== 1 ? "s" : ""} in this window
            (rate-limit, server error, or refusal)
          </span>
        </div>
      )}

      {/* per-value trend charts */}
      <MetricGrid
        totals={totals}
        series={series}
        bySource={series_by_source}
        nowBucket={now_bucket}
        bucketSize={bucket_size}
      />

      {/* queue backlog (current depth) */}
      <QueueWidget queue={queue} />

      {/* detail: where each number came from */}
      <BreakdownTables totals={totals} />
    </div>
  );
}
