import { useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { X, Play, Loader2 } from "lucide-react";
import { getQueryDetail, replayQuery } from "../api/client";
import type { QueryResultRow } from "../api/types";
import { ResultRow } from "./ResultRow";

const MODE_TONE: Record<string, string> = {
  hybrid: "bg-accent/15 text-accent",
  vector: "bg-sky-400/15 text-sky-300",
  bm25: "bg-warn/15 text-warn",
  graph: "bg-fuchsia-400/15 text-fuchsia-300",
  multi: "bg-run/15 text-run",
};

/**
 * Right-hand drawer showing a logged query's full text + ranked results, with
 * a Re-run button that replays the query live against the running server.
 */
export function QueryDrawer({
  instanceId,
  qid,
  onClose,
}: {
  instanceId: string;
  qid: string | null;
  onClose: () => void;
}) {
  const detailQ = useQuery({
    queryKey: ["query-detail", instanceId, qid],
    queryFn: () => getQueryDetail(instanceId, qid!),
    enabled: !!qid,
    retry: false,
  });

  const replayM = useMutation({
    mutationFn: () => {
      const d = detailQ.data!;
      return replayQuery(instanceId, {
        query: d.query,
        mode: d.mode,
        top_k: d.top_k,
      });
    },
  });

  useEffect(() => {
    if (!qid) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [qid, onClose]);

  // Reset any prior replay when switching queries.
  useEffect(() => {
    replayM.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [qid]);

  if (!qid) return null;

  const d = detailQ.data;
  const replayed = replayM.data;
  const fresh: QueryResultRow[] | null = replayed
    ? replayed.results.map((r) => ({
        score: r.score,
        path: r.source,
        lines: null,
        snippet: r.text,
      }))
    : null;

  return (
    <div className="fixed inset-0 z-50" role="presentation">
      <div
        className="absolute inset-0 bg-ink-900/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="h2-query-drawer-title"
        data-testid="query-drawer"
        className="panel animate-fade-up absolute right-0 top-0 flex h-full w-full max-w-xl flex-col rounded-none border-y-0 border-r-0 p-6"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="eyebrow">Query detail</p>
            <h2
              id="h2-query-drawer-title"
              className="mt-1 break-words font-display text-base font-semibold tracking-tight"
            >
              {d?.query ?? "Loading…"}
            </h2>
          </div>
          <button
            type="button"
            data-testid="btn-drawer-close"
            onClick={onClose}
            aria-label="Close"
            className="text-fg-faint transition-colors hover:text-fg"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        {d && (
          <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
            <span
              className={`rounded-md px-2 py-0.5 font-mono uppercase tracking-wider ${MODE_TONE[d.mode] ?? "bg-ink-600 text-fg-muted"}`}
            >
              {d.mode}
            </span>
            <span className="rounded-md bg-ink-600 px-2 py-0.5 text-fg-muted">
              top_k {d.top_k}
            </span>
            <span className="rounded-md bg-ink-600 px-2 py-0.5 text-fg-muted">
              {Math.round(d.latency_ms)} ms
            </span>
            <span className="rounded-md bg-ink-600 px-2 py-0.5 text-fg-muted">
              {d.result_count} results
            </span>
            <button
              type="button"
              data-testid="btn-rerun"
              onClick={() => replayM.mutate()}
              disabled={replayM.isPending}
              className="btn-primary btn-sm ml-auto"
            >
              {replayM.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
              ) : (
                <Play className="h-3.5 w-3.5" aria-hidden="true" />
              )}
              Re-run
            </button>
          </div>
        )}

        <div className="mt-5 min-h-0 flex-1 overflow-y-auto">
          {detailQ.isLoading && <div className="skeleton h-24 w-full" />}
          {fresh ? (
            <div data-testid="replay-results">
              <p className="eyebrow mb-2 text-run">
                Fresh results · {replayed!.total_results} hits ·{" "}
                {Math.round(replayed!.query_time_ms)} ms
              </p>
              <ul className="flex flex-col gap-2">
                {fresh.map((r, i) => (
                  <ResultRow
                    key={i}
                    path={r.path}
                    lines={r.lines}
                    snippet={r.snippet}
                    score={r.score}
                  />
                ))}
              </ul>
            </div>
          ) : (
            d && (
              <div data-testid="logged-results">
                <p className="eyebrow mb-2">Logged results</p>
                {d.results.length === 0 ? (
                  <p className="text-sm text-fg-faint">No results were logged.</p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {d.results.map((r, i) => (
                      <ResultRow
                        key={i}
                        path={r.path}
                        lines={r.lines}
                        snippet={r.snippet}
                        score={r.score}
                      />
                    ))}
                  </ul>
                )}
              </div>
            )
          )}
          {replayM.isError && (
            <p
              data-testid="replay-error"
              className="mt-3 rounded-lg border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad"
            >
              Re-run failed: {(replayM.error as Error).message}
            </p>
          )}
        </div>
      </aside>
    </div>
  );
}
