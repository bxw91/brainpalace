import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Search, Plus, Play, Loader2, X } from "lucide-react";
import { getQueries, replayQuery } from "../api/client";
import type { QueryRow } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { QueryDrawer } from "../components/QueryDrawer";
import { VolumeChart, LatencyChart, type TimeSeriesDatum } from "../components/Charts";
import { CompareGrid, type CompareRun } from "../components/CompareGrid";
import { ResultRow } from "../components/ResultRow";
import { QueryAnalytics } from "../components/QueryAnalytics";
import { useOptionalSelectedInstance } from "../state/selectedInstance";
import { useToast } from "../components/Toast";
import { useDisplayFormat } from "../format/datetime";
import {
  NoInstance,
  StoppedState,
  ErrorState,
  TabSkeleton,
  isUnreachable,
} from "../components/TabState";

const RUN_MODES = [
  "hybrid",
  "vector",
  "bm25",
  "graph",
  "multi",
  "compute",
  "scan",
  "absence",
  "timeline",
] as const;

const COMPARE_MODES = ["bm25", "vector", "hybrid", "graph"] as const;
const RERANK_OPTIONS = [
  { value: "default", label: "reranker: server default" },
  { value: "on", label: "reranker: on" },
  { value: "off", label: "reranker: off" },
] as const;

const MODES = ["all", "hybrid", "vector", "bm25", "graph", "multi"] as const;
const RANGES = [
  { key: "24h", label: "24h", days: 1 },
  { key: "2d", label: "2d", days: 2 },
  { key: "7d", label: "7d", days: 7 },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];

const MODE_TONE: Record<string, string> = {
  hybrid: "bg-accent/15 text-accent",
  vector: "bg-sky-400/15 text-sky-300",
  bm25: "bg-warn/15 text-warn",
  graph: "bg-fuchsia-400/15 text-fuchsia-300",
  multi: "bg-run/15 text-run",
};

function relTime(ts: number): string {
  const secs = Math.round(Date.now() / 1000 - ts);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

/** Bucket rows into hourly (<=2d) or daily (>2d) buckets for the charts. */
function bucketize(
  rows: QueryRow[],
  days: number,
  fmtDay: (d: Date) => string,
  fmtHour: (d: Date) => string,
): {
  volume: TimeSeriesDatum[];
  latency: TimeSeriesDatum[];
} {
  if (rows.length === 0) return { volume: [], latency: [] };
  const daily = days > 2;
  const fmt = (ts: number) => {
    const d = new Date(ts * 1000);
    return daily ? fmtDay(d) : fmtHour(d);
  };
  const order: string[] = [];
  const counts = new Map<string, number>();
  const lat = new Map<string, { sum: number; n: number }>();
  // oldest -> newest for left-to-right charts.
  [...rows].sort((a, b) => a.ts - b.ts).forEach((r) => {
    const key = fmt(r.ts);
    if (!counts.has(key)) {
      order.push(key);
      counts.set(key, 0);
      lat.set(key, { sum: 0, n: 0 });
    }
    counts.set(key, counts.get(key)! + 1);
    const l = lat.get(key)!;
    l.sum += r.latency_ms;
    l.n += 1;
  });
  return {
    volume: order.map((k) => ({ label: k, value: counts.get(k)! })),
    latency: order.map((k) => {
      const l = lat.get(k)!;
      return { label: k, value: Math.round(l.sum / Math.max(1, l.n)) };
    }),
  };
}

export function Queries({ instanceId }: { instanceId?: string }) {
  const ctx = useOptionalSelectedInstance();
  const id = instanceId ?? ctx?.selectedId ?? null;
  const qc = useQueryClient();
  const { toast } = useToast();

  const [mode, setMode] = useState<string>("all");
  const [range, setRange] = useState<RangeKey>("24h");
  const [contains, setContains] = useState("");
  const [openQid, setOpenQid] = useState<string | null>(null);

  // "New query" composer: run a live query against the server. The server logs
  // it, so it also lands in history once we invalidate the list.
  const [composerOpen, setComposerOpen] = useState(false);
  const [runText, setRunText] = useState("");
  const [runMode, setRunMode] = useState<string>("hybrid");
  const [compare, setCompare] = useState(false);
  const [rerankOpt, setRerankOpt] = useState<string>("default");
  const [compareRuns, setCompareRuns] = useState<CompareRun[] | null>(null);

  const rerankFlag: boolean | undefined =
    rerankOpt === "default" ? undefined : rerankOpt === "on";

  const days = RANGES.find((r) => r.key === range)!.days;
  const since = Math.floor(Date.now() / 1000 - days * 86400);

  const queriesQ = useQuery({
    queryKey: ["queries", id, mode, range, contains],
    queryFn: () =>
      getQueries(id!, {
        since,
        limit: 500,
        ...(mode !== "all" ? { mode } : {}),
        ...(contains.trim() ? { contains: contains.trim() } : {}),
      }),
    enabled: !!id,
    retry: false,
  });

  const runM = useMutation({
    mutationFn: async () => {
      const base = { query: runText.trim(), top_k: 5 } as const;
      const body = (mode: string) => ({
        ...base,
        mode,
        ...(rerankFlag !== undefined ? { rerank: rerankFlag } : {}),
      });
      if (!compare) return replayQuery(id!, body(runMode));
      setCompareRuns(COMPARE_MODES.map((m) => ({ mode: m, pending: true })));
      const settled = await Promise.allSettled(
        COMPARE_MODES.map((m) => replayQuery(id!, body(m))),
      );
      setCompareRuns(
        COMPARE_MODES.map((m, i) => {
          const s = settled[i];
          return s.status === "fulfilled"
            ? { mode: m, pending: false, data: s.value }
            : {
                mode: m,
                pending: false,
                error: s.reason instanceof Error ? s.reason.message : "failed",
              };
        }),
      );
      return undefined;
    },
    onSuccess: () => {
      toast("Query ran.", "success");
      qc.invalidateQueries({ queryKey: ["queries", id] });
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Query failed.", "error"),
  });

  const { formatShortDate, formatHour } = useDisplayFormat();
  const rows = queriesQ.data ?? [];
  const charts = useMemo(
    () => bucketize(rows, days, formatShortDate, formatHour),
    [rows, days, formatShortDate, formatHour],
  );

  const columns: Column<QueryRow>[] = [
    {
      key: "ts",
      header: "When",
      cell: (r) => <span className="text-xs text-fg-muted">{relTime(r.ts)}</span>,
      sortValue: (r) => r.ts,
    },
    {
      key: "mode",
      header: "Mode",
      cell: (r) => (
        <span
          className={`rounded-md px-2 py-0.5 font-mono text-[0.66rem] uppercase tracking-wider ${MODE_TONE[r.mode] ?? "bg-ink-600 text-fg-muted"}`}
        >
          {r.mode}
        </span>
      ),
      sortValue: (r) => r.mode,
    },
    {
      key: "query",
      header: "Query",
      cell: (r) => (
        <span className="block max-w-md truncate text-fg" title={r.query}>
          {r.query}
        </span>
      ),
      sortValue: (r) => r.query,
    },
    {
      key: "latency",
      header: "Latency",
      align: "right",
      cell: (r) => (
        <span className="tabular-nums text-fg-muted">{Math.round(r.latency_ms)} ms</span>
      ),
      sortValue: (r) => r.latency_ms,
    },
    {
      key: "results",
      header: "Hits",
      align: "right",
      cell: (r) => <span className="tabular-nums">{r.result_count}</span>,
      sortValue: (r) => r.result_count,
    },
  ];

  if (!id) {
    return <NoInstance testId="tab-queries" message="Select an instance to browse its query history." />;
  }
  if (isUnreachable(queriesQ.error)) {
    return <StoppedState testId="queries-stopped" />;
  }
  if (queriesQ.isError) {
    return (
      <ErrorState
        testId="queries-error"
        message={(queriesQ.error as Error)?.message}
        onRetry={() => queriesQ.refetch()}
        retrying={queriesQ.isFetching}
      />
    );
  }
  if (queriesQ.isLoading) {
    return (
      <div data-testid="tab-queries">
        <TabSkeleton rows={2} />
      </div>
    );
  }

  const runResults = runM.data;

  return (
    <div data-testid="tab-queries" className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="eyebrow">Query history</p>
          <h2 className="mt-0.5 font-display text-base font-semibold tracking-tight">
            Browse, filter and replay past queries
          </h2>
        </div>
        <button
          type="button"
          data-testid="btn-new-query"
          onClick={() => setComposerOpen((v) => !v)}
          className="btn-primary btn-sm"
          aria-expanded={composerOpen}
        >
          <Plus className="h-4 w-4" aria-hidden="true" /> New query
        </button>
      </div>

      {composerOpen && (
        <div data-testid="query-composer" className="panel flex flex-col gap-3 p-5">
          <div className="flex items-center justify-between">
            <p className="eyebrow">Run a query</p>
            <button
              type="button"
              data-testid="btn-composer-close"
              onClick={() => setComposerOpen(false)}
              aria-label="Close query composer"
              className="text-fg-faint transition-colors hover:text-fg"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-0 flex-1">
              <label
                htmlFor="input-run-query"
                className="mb-1.5 block text-xs font-medium text-fg-muted"
              >
                Query
              </label>
              <input
                id="input-run-query"
                data-testid="input-run-query"
                type="text"
                value={runText}
                placeholder="Ask the index something…"
                onChange={(e) => setRunText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && runText.trim() && !runM.isPending) {
                    runM.mutate();
                  }
                }}
                className="w-full rounded-lg border border-line bg-ink-900/50 px-3 py-2 text-sm text-fg outline-none transition-colors placeholder:text-fg-faint focus:border-accent/50 focus:ring-2 focus:ring-accent/30"
              />
            </div>
            <div>
              <label
                htmlFor="select-run-mode"
                className="mb-1.5 block text-xs font-medium text-fg-muted"
              >
                Mode
              </label>
              <select
                id="select-run-mode"
                data-testid="select-run-mode"
                value={runMode}
                disabled={compare}
                onChange={(e) => setRunMode(e.target.value)}
                className="rounded-lg border border-line bg-ink-900/50 px-3 py-2 text-sm text-fg focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
              >
                {RUN_MODES.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label
                htmlFor="select-rerank"
                className="mb-1.5 block text-xs font-medium text-fg-muted"
              >
                Reranker
              </label>
              <select
                id="select-rerank"
                data-testid="select-rerank"
                value={rerankOpt}
                onChange={(e) => setRerankOpt(e.target.value)}
                className="rounded-lg border border-line bg-ink-900/50 px-3 py-2 text-sm text-fg focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
              >
                {RERANK_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="button"
              data-testid="toggle-compare"
              aria-pressed={compare}
              onClick={() => setCompare((v) => !v)}
              className={compare ? "btn-primary btn-sm" : "btn-ghost btn-sm"}
            >
              Compare modes
            </button>
            <button
              type="button"
              data-testid="btn-run-query"
              disabled={!runText.trim() || runM.isPending}
              onClick={() => runM.mutate()}
              className="btn-primary btn-sm"
            >
              {runM.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Play className="h-4 w-4" aria-hidden="true" />
              )}
              Run
            </button>
          </div>

          {!compare && runResults && (
            <div data-testid="run-results" className="mt-1">
              <p className="eyebrow mb-2 text-run">
                {runResults.total_results} result
                {runResults.total_results === 1 ? "" : "s"} ·{" "}
                {Math.round(runResults.query_time_ms)} ms
              </p>
              {(() => {
                if (runResults.timeline != null) {
                  return runResults.timeline.length === 0 ? (
                    <p className="text-sm text-fg-faint">
                      No history found — no recognizable entity, or it has no graph
                      edges.
                    </p>
                  ) : (
                    <ul className="flex flex-col gap-1.5">
                      {runResults.timeline.slice(0, 12).map((r, i) => (
                        <li
                          key={i}
                          className="rounded-lg border border-line/60 bg-ink-700/30 px-3 py-2 font-mono text-xs text-fg-muted"
                        >
                          {`${r.valid === false ? "✗" : "✓"} ${r.subject} —${r.predicate}→ ${r.object} (${r.valid_from ?? "?"} … ${r.valid_until ?? "now"})`}
                        </li>
                      ))}
                    </ul>
                  );
                }
                if (runResults.absence != null) {
                  return runResults.absence.length === 0 ? (
                    <p className="text-sm text-fg-faint">No gaps found.</p>
                  ) : (
                    <ul className="flex flex-col gap-1.5">
                      {runResults.absence.slice(0, 10).map((r, i) => (
                        <li
                          key={i}
                          className="rounded-lg border border-line/60 bg-ink-700/30 px-3 py-2 font-mono text-xs text-fg-muted"
                        >
                          {`${r.label} (in ${r.present_in}, not ${r.absent_from})`}
                        </li>
                      ))}
                    </ul>
                  );
                }
                const isScan = runResults.scan != null;
                const agg = runResults.compute ?? runResults.scan;
                if (agg != null) {
                  return agg.length === 0 ? (
                    isScan ? (
                      <div
                        data-testid="scan-empty-hint"
                        className="rounded-lg border border-line/60 bg-ink-700/30 px-3 py-2.5 text-sm text-fg-muted"
                      >
                        <p>
                          No matches. <span className="font-mono">scan</span> counts one
                          term over your archived sessions. A{" "}
                          <em>single word</em> is counted as-is; for a{" "}
                          <em>multi-word phrase</em> quote it (
                          <span className="font-mono text-fg-muted">
                            "entity resolution"
                          </span>
                          ) or use a "mention" tell.
                        </p>
                        <p className="mt-1.5 text-fg-faint">
                          Otherwise the term never appears, or the session archive is
                          off. To <em>locate</em> a session containing a term (not count
                          it), use <span className="font-mono text-fg-muted">bm25</span>{" "}
                          mode.
                        </p>
                      </div>
                    ) : (
                      <p className="text-sm text-fg-faint">No aggregation rows.</p>
                    )
                  ) : (
                    <ul className="flex flex-col gap-1.5">
                      {agg.slice(0, 10).map((r, i) => (
                        <li
                          key={i}
                          className="rounded-lg border border-line/60 bg-ink-700/30 px-3 py-2 font-mono text-xs text-fg-muted"
                        >
                          {r.label}: {r.value}
                        </li>
                      ))}
                    </ul>
                  );
                }
                return runResults.results.length === 0 ? (
                  <p className="text-sm text-fg-faint">No matching chunks.</p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {runResults.results.map((r, i) => (
                      <ResultRow
                        key={i}
                        path={r.source}
                        lines={null}
                        snippet={r.text}
                        score={r.score}
                      />
                    ))}
                  </ul>
                );
              })()}
            </div>
          )}

          {compare && compareRuns && <CompareGrid runs={compareRuns} />}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="panel p-5">
          <p className="eyebrow mb-3">Query volume</p>
          <VolumeChart data={charts.volume} />
        </div>
        <div className="panel p-5">
          <p className="eyebrow mb-3">Latency (avg ms)</p>
          <LatencyChart data={charts.latency} />
        </div>
      </div>

      <QueryAnalytics
        instanceId={id}
        since={since}
        windowKey={range}
        onSelectQuery={setOpenQid}
      />

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5">
          {RANGES.map((r) => (
            <button
              key={r.key}
              type="button"
              data-testid={`btn-range-${r.key}`}
              onClick={() => setRange(r.key)}
              className={
                range === r.key
                  ? "btn-primary btn-sm"
                  : "btn-ghost btn-sm"
              }
            >
              {r.label}
            </button>
          ))}
        </div>

        <label htmlFor="select-mode" className="sr-only">
          Filter by mode
        </label>
        <select
          id="select-mode"
          data-testid="select-mode"
          value={mode}
          onChange={(e) => setMode(e.target.value)}
          className="rounded-lg border border-line bg-ink-700/50 px-3 py-1.5 text-sm text-fg focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
        >
          {MODES.map((m) => (
            <option key={m} value={m}>
              {m === "all" ? "all modes" : m}
            </option>
          ))}
        </select>

        <div className="relative ml-auto">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-faint"
            aria-hidden="true"
          />
          <label htmlFor="input-contains" className="sr-only">
            Search queries
          </label>
          <input
            id="input-contains"
            data-testid="input-contains"
            type="text"
            value={contains}
            onChange={(e) => setContains(e.target.value)}
            placeholder="Search query text…"
            className="w-64 rounded-lg border border-line bg-ink-700/50 py-1.5 pl-9 pr-3 text-sm text-fg placeholder:text-fg-faint focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
          />
        </div>
      </div>

      <DataTable<QueryRow>
        rows={rows}
        columns={columns}
        rowKey={(r) => r.id}
        rowTestId={(r) => `query-row-${r.id}`}
        onRowClick={(r) => setOpenQid(r.id)}
        empty="No queries logged in this window."
        trailing={{
          header: "",
          cell: (r) => (
            <button
              type="button"
              data-testid={`btn-open-${r.id}`}
              onClick={(e) => {
                e.stopPropagation();
                setOpenQid(r.id);
              }}
              className="btn-ghost btn-sm"
            >
              View
            </button>
          ),
        }}
      />

      <QueryDrawer instanceId={id} qid={openQid} onClose={() => setOpenQid(null)} />
    </div>
  );
}
