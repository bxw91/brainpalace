import type { JobRow } from "../api/types";

const ACTIVE = new Set(["queued", "running", "pending"]);

export function isJobActive(j: JobRow): boolean {
  return ACTIVE.has(j.status.toLowerCase());
}

/**
 * Inline progress strip for the currently-active indexing job. Rendered above
 * the folder table while a job is queued/running; hidden otherwise. The percent
 * comes straight from the server's `progress_percent`.
 */
export function JobProgress({ jobs }: { jobs: JobRow[] }) {
  const active = jobs.find(isJobActive);
  if (!active) return null;
  const pct = Math.max(0, Math.min(100, Math.round(active.progress_percent ?? 0)));
  const folder = active.folder_path.split("/").filter(Boolean).pop() ?? active.folder_path;

  return (
    <div
      id="div-job-progress"
      data-testid="job-progress"
      className="panel animate-fade-up flex flex-col gap-2 p-4"
    >
      <div className="flex items-center justify-between text-sm">
        <span className="flex items-center gap-2">
          <span className="h-2 w-2 animate-pulse-dot rounded-full bg-accent" aria-hidden="true" />
          <span className="font-medium text-fg">
            {active.operation === "index" ? "Indexing" : active.operation} {folder}
          </span>
          <span className="font-mono text-xs uppercase tracking-wider text-fg-faint">
            {active.status}
          </span>
        </span>
        <span data-testid="job-progress-pct" className="font-mono tabular-nums text-accent">
          {pct}%
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-ink-600">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-500"
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>
    </div>
  );
}
