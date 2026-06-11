import { useQuery } from "@tanstack/react-query";
import { getQueryStats } from "../api/client";
import { PercentileChart } from "./Charts";
import { StatCard } from "./StatCard";

const MODE_BAR_TONE: Record<string, string> = {
  hybrid: "bg-accent",
  vector: "bg-sky-400",
  bm25: "bg-warn",
  graph: "bg-fuchsia-400",
  multi: "bg-run",
};

/**
 * Analytics over the query log: totals, mode distribution, p50/p95 trend,
 * top queries and zero-result queries (index gaps). Lives in the Queries tab
 * below the volume/latency charts and shares its `since` window.
 *
 * `windowKey` (the range key, e.g. "24h") is used for the queryKey instead of
 * `since`: the tab recomputes `since` from Date.now() on every render, so
 * keying on it would refetch on every unrelated re-render. Mirrors how the
 * tab's own history query keys on `range`, not `since`.
 */
export function QueryAnalytics({
  instanceId,
  since,
  windowKey,
  onSelectQuery,
}: {
  instanceId: string;
  since: number;
  windowKey: string;
  /** Open a query's detail drawer (same view as a history-table row click). */
  onSelectQuery?: (qid: string) => void;
}) {
  const statsQ = useQuery({
    queryKey: ["query-stats", instanceId, windowKey],
    queryFn: () => getQueryStats(instanceId, { since, top_n: 10 }),
    retry: false,
  });

  const s = statsQ.data;
  if (!s) return null;

  const modeTotal = Object.values(s.mode_distribution).reduce((a, b) => a + b, 0);

  return (
    <div data-testid="query-analytics" className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Queries" value={String(s.total)} testId="analytics-total" />
        <StatCard
          label="Zero-result"
          value={String(s.zero_result_count)}
          testId="analytics-zero"
        />
        <StatCard label="p50 latency" value={`${Math.round(s.latency.p50)} ms`} />
        <StatCard label="p95 latency" value={`${Math.round(s.latency.p95)} ms`} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="panel p-5">
          <p className="eyebrow mb-3">Latency p50 / p95</p>
          <PercentileChart
            data={s.latency_trend.map((b) => ({
              label: b.bucket.slice(11),
              p50: b.p50,
              p95: b.p95,
            }))}
          />
        </div>
        <div className="panel p-5">
          <p className="eyebrow mb-3">Mode distribution</p>
          <ul className="flex flex-col gap-2">
            {Object.entries(s.mode_distribution)
              .sort(([, a], [, b]) => b - a)
              .map(([mode, n]) => (
                <li key={mode} className="flex items-center gap-3">
                  <span className="w-16 font-mono text-xs uppercase text-fg-muted">
                    {mode}
                  </span>
                  <span className="h-2 flex-1 overflow-hidden rounded bg-ink-700">
                    <span
                      className={`block h-full ${MODE_BAR_TONE[mode] ?? "bg-fg-faint"}`}
                      style={{ width: `${(n / Math.max(1, modeTotal)) * 100}%` }}
                    />
                  </span>
                  <span
                    data-testid={`mode-dist-${mode}`}
                    className="w-10 text-right font-mono text-xs tabular-nums"
                  >
                    {n}
                  </span>
                </li>
              ))}
          </ul>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="panel p-5">
          <p className="eyebrow mb-3">Top queries</p>
          {s.top_queries.length === 0 ? (
            <p className="text-sm text-fg-faint">No queries in this window.</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {s.top_queries.map((t) => (
                <li key={t.query}>
                  <button
                    type="button"
                    data-testid={`top-query-${t.query}`}
                    onClick={() => onSelectQuery?.(t.last_id)}
                    disabled={!onSelectQuery}
                    className="flex w-full items-center gap-3 rounded text-left text-sm enabled:hover:text-accent disabled:cursor-default"
                  >
                    <span className="flex-1 truncate" title={t.query}>
                      {t.query}
                    </span>
                    <span className="font-mono text-xs text-fg-muted">
                      ×{t.count} · {Math.round(t.avg_latency_ms)} ms
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="panel p-5">
          <p className="eyebrow mb-3">Zero-result queries (index gaps)</p>
          {s.zero_result_queries.length === 0 ? (
            <p className="text-sm text-fg-faint">None — every query matched.</p>
          ) : (
            <ul className="flex flex-col gap-1.5">
              {s.zero_result_queries.map((z) => (
                <li key={z.query} className="flex items-center gap-3 text-sm">
                  <span className="flex-1 truncate text-warn" title={z.query}>
                    {z.query}
                  </span>
                  <span className="font-mono text-xs text-fg-muted">×{z.count}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
