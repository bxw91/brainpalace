import type { ReplayResponse, ReplayResult } from "../api/types";

export type CompareRun = {
  mode: string;
  pending: boolean;
  error?: string;
  data?: ReplayResponse;
};

const fmtScore = (v: number | null | undefined) =>
  v == null ? "–" : v.toFixed(3);

function ScoreChips({ r }: { r: ReplayResult }) {
  const chips: Array<[string, number | null | undefined]> = [
    ["score", r.score],
    ["vec", r.vector_score],
    ["bm25", r.bm25_score],
    ["graph", r.graph_score],
    ["rerank", r.rerank_score],
  ];
  return (
    <span className="flex flex-wrap gap-1">
      {chips
        .filter(([, v]) => v != null)
        .map(([label, v]) => (
          <span
            key={label}
            className="rounded bg-ink-600 px-1.5 py-0.5 font-mono text-[0.6rem] text-fg-muted"
          >
            {label} {fmtScore(v)}
          </span>
        ))}
      {r.original_rank != null && (
        <span className="rounded bg-warn/15 px-1.5 py-0.5 font-mono text-[0.6rem] text-warn">
          was #{r.original_rank}
        </span>
      )}
    </span>
  );
}

/**
 * Side-by-side per-mode result columns for the Retrieval Explorer.
 * Chunks returned by 2+ modes get a "shared" badge so overlap is visible.
 */
export function CompareGrid({ runs }: { runs: CompareRun[] }) {
  const chunkModeCount = new Map<string, number>();
  runs.forEach((run) =>
    run.data?.results.forEach((r) => {
      chunkModeCount.set(r.chunk_id, (chunkModeCount.get(r.chunk_id) ?? 0) + 1);
    }),
  );

  return (
    <div
      data-testid="compare-grid"
      className="grid gap-3 md:grid-cols-2 xl:grid-cols-4"
    >
      {runs.map((run) => (
        <div
          key={run.mode}
          data-testid={`compare-col-${run.mode}`}
          className="panel flex flex-col gap-2 p-3"
        >
          <p className="eyebrow flex items-center justify-between">
            <span>{run.mode}</span>
            {run.data && (
              <span className="font-mono text-[0.65rem] text-fg-faint">
                {run.data.total_results} hits · {Math.round(run.data.query_time_ms)} ms
              </span>
            )}
          </p>
          {run.pending && <p className="text-sm text-fg-faint">Running…</p>}
          {run.error && (
            <p data-testid={`compare-error-${run.mode}`} className="text-sm text-warn">
              {run.error}
            </p>
          )}
          {run.data && run.data.results.length === 0 && (
            <p className="text-sm text-fg-faint">No matching chunks.</p>
          )}
          {run.data && (
            <ul className="flex flex-col gap-1.5">
              {run.data.results.map((r) => (
                <li
                  key={r.chunk_id}
                  className="rounded-lg border border-line/60 bg-ink-700/30 px-2.5 py-2"
                >
                  <span
                    className="block truncate font-mono text-xs text-fg"
                    title={r.source}
                  >
                    {r.source}
                  </span>
                  <span className="mt-1 flex items-center gap-1.5">
                    {(chunkModeCount.get(r.chunk_id) ?? 0) > 1 && (
                      <span className="rounded bg-accent/15 px-1.5 py-0.5 text-[0.6rem] text-accent">
                        shared
                      </span>
                    )}
                    <ScoreChips r={r} />
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}
