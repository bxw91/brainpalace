/**
 * Shared ranked-result row: file location, score bar and a scrollable snippet.
 * Used by the query-detail drawer AND the live "New query" composer so both
 * render the same detail (path · score · snippet), not just a bare file list.
 */
export function ScoreBar({ score }: { score: number | null }) {
  const pct = score == null ? 0 : Math.max(0, Math.min(100, Math.round(score * 100)));
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-ink-600">
        <div className="h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-[0.68rem] tabular-nums text-fg-faint">
        {score == null ? "—" : score.toFixed(3)}
      </span>
    </div>
  );
}

export function ResultRow({
  path,
  lines,
  snippet,
  score,
}: {
  path: string | null;
  lines: [number, number] | null;
  snippet: string;
  score: number | null;
}) {
  const loc = path ? (lines ? `${path}:${lines[0]}-${lines[1]}` : path) : "(unknown)";
  return (
    <li className="rounded-lg border border-line/60 bg-ink-700/30 p-3">
      <div className="flex items-center justify-between gap-3">
        <span className="truncate font-mono text-xs text-fg" title={loc}>
          {loc}
        </span>
        <ScoreBar score={score} />
      </div>
      {snippet && (
        <pre className="scroll-visible mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded bg-ink-900/60 p-2 font-mono text-[0.7rem] leading-relaxed text-fg-muted">
          {snippet}
        </pre>
      )}
    </li>
  );
}
