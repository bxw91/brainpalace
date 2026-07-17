import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { getJobDetail } from "../api/client";
import type { JobDetail } from "../api/types";
import { useDisplayFormat } from "../format/datetime";

const STATUS_TONE: Record<string, string> = {
  running: "bg-accent/15 text-accent",
  queued: "bg-warn/15 text-warn",
  pending: "bg-warn/15 text-warn",
  done: "bg-run/15 text-run",
  error: "bg-bad/15 text-bad",
  failed: "bg-bad/15 text-bad",
  blocked: "bg-warn/15 text-warn",
  cancelled: "bg-ink-600 text-fg-muted",
};

function fmtTime(
  iso: string | null,
  formatDateTime: (d: Date) => string,
): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : formatDateTime(d);
}

function fmtDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s % 60)}s`;
}

/** A labelled stat tile in the results grid. */
function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-line/60 bg-ink-700/30 p-3">
      <p className="eyebrow text-fg-faint">{label}</p>
      <p className="mt-1 font-mono text-sm tabular-nums text-fg">{value}</p>
    </div>
  );
}

/** Show the full file list inline only below this count; at/above it the list
 *  is collapsed behind a "Show all" button so a large job (e.g. 911 unchanged
 *  files) doesn't flood the drawer. */
const FILE_LIST_INLINE_MAX = 20;

/**
 * A named list of file paths from a job's eviction summary (added / changed /
 * deleted / unchanged). Every path is shown in full — never truncated (paths
 * wrap via `break-all`) — and the list collapses behind a button once it has
 * `FILE_LIST_INLINE_MAX` or more entries.
 */
function FileList({ label, files }: { label: string; files: string[] }) {
  const [expanded, setExpanded] = useState(false);
  if (files.length === 0) return null;
  const collapsed = files.length >= FILE_LIST_INLINE_MAX && !expanded;
  const niceLabel = label.replace(/^files_/, "").replace(/_/g, " ");
  return (
    <div className="mt-3" data-testid={`file-list-${label}`}>
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-xs text-fg-faint">
          {niceLabel}{" "}
          <span className="font-mono tabular-nums text-fg-muted">
            ({files.length})
          </span>
        </p>
        {collapsed && (
          <button
            type="button"
            data-testid={`btn-show-all-${label}`}
            onClick={() => setExpanded(true)}
            className="text-xs font-medium text-accent transition-colors hover:underline"
          >
            Show all {files.length} files
          </button>
        )}
      </div>
      {!collapsed && (
        <ul
          data-testid={`file-list-items-${label}`}
          className="mt-1 max-h-72 space-y-0.5 overflow-y-auto rounded-lg border border-line/60 bg-ink-700/20 p-2"
        >
          {files.map((f) => (
            <li
              key={f}
              className="whitespace-pre-wrap break-all font-mono text-[11px] leading-snug text-fg-muted"
            >
              {f}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** One key/value row in the metadata list. */
function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-line/40 py-2 last:border-0">
      <span className="text-xs text-fg-faint">{label}</span>
      <span className="truncate font-mono text-xs text-fg-muted" title={value}>
        {value}
      </span>
    </div>
  );
}

/**
 * Right-hand drawer showing what a single indexing job did: documents/chunks
 * indexed, duration, files processed, and the eviction (added/changed/deleted)
 * breakdown. Read-only — fetches `/index/jobs/{job_id}` via the BFF.
 */
export function JobDrawer({
  instanceId,
  jobId,
  onClose,
}: {
  instanceId: string;
  jobId: string | null;
  onClose: () => void;
}) {
  const { formatDateTime } = useDisplayFormat();
  const detailQ = useQuery({
    queryKey: ["job-detail", instanceId, jobId],
    queryFn: () => getJobDetail(instanceId, jobId!),
    enabled: !!jobId,
    retry: false,
    // Keep an active job's detail fresh while it runs.
    refetchInterval: (q) => {
      const s = (q.state.data as JobDetail | undefined)?.status;
      return s === "running" || s === "pending" || s === "queued" ? 2000 : false;
    },
  });

  useEffect(() => {
    if (!jobId) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [jobId, onClose]);

  if (!jobId) return null;

  const d = detailQ.data;
  const evictionEntries = d?.eviction_summary
    ? Object.entries(d.eviction_summary)
    : [];
  // Added/changed/deleted are what the job DID (small, actionable) and stay
  // as expandable file lists. Unchanged is what it SKIPPED -- a per-file
  // list of it is low-value noise (seen: 90-911 entries burying everything
  // below it), so it's excluded from fileLists and shown only as a count.
  const evictions = [
    ...(evictionEntries.filter(([, v]) => typeof v === "number") as [
      string,
      number,
    ][]),
    ...(evictionEntries.filter(
      ([k, v]) => k === "files_unchanged" && Array.isArray(v),
    ) as [string, string[]][]).map(
      ([k, v]) => [k, v.length] as [string, number],
    ),
  ];
  const fileLists = evictionEntries.filter(
    ([k, v]) => k !== "files_unchanged" && Array.isArray(v) && v.length > 0,
  ) as [string, string[]][];

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
        aria-labelledby="h2-job-drawer-title"
        data-testid="job-drawer"
        className="panel animate-fade-up absolute right-0 top-0 flex h-full w-full max-w-xl flex-col rounded-none border-y-0 border-r-0 p-6"
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="eyebrow">Job detail</p>
            <h2
              id="h2-job-drawer-title"
              className="mt-1 break-all font-display text-base font-semibold tracking-tight"
            >
              {jobId}
            </h2>
          </div>
          <button
            type="button"
            data-testid="btn-job-drawer-close"
            onClick={onClose}
            aria-label="Close"
            className="text-fg-faint transition-colors hover:text-fg"
          >
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        {d && (
          <div data-testid="job-drawer-header">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span
                className={`rounded-md px-2 py-0.5 font-mono uppercase tracking-wider ${STATUS_TONE[d.status] ?? "bg-ink-600 text-fg-muted"}`}
              >
                {d.status}
              </span>
              <span className="rounded-md bg-ink-600 px-2 py-0.5 text-fg-muted">
                {d.operation}
              </span>
              <span className="rounded-md bg-ink-600 px-2 py-0.5 text-fg-muted">
                {d.source}
              </span>
              {d.include_code && (
                <span className="rounded-md bg-ink-600 px-2 py-0.5 text-fg-muted">
                  code
                </span>
              )}
            </div>
            {/* Folder, up top next to the status chips — a job is
                single-folder, so surfacing it here (not only at the bottom
                of the Details block) means it's not scrolled off-screen
                below a large Files list. */}
            <p
              className="mt-2 truncate break-all font-mono text-xs text-fg-muted"
              title={d.folder_path}
            >
              {d.folder_path}
            </p>
          </div>
        )}

        <div className="mt-5 min-h-0 flex-1 overflow-y-auto">
          {detailQ.isLoading && <div className="skeleton h-24 w-full" />}
          {detailQ.isError && (
            <p
              data-testid="job-detail-error"
              className="rounded-lg border border-bad/30 bg-bad/10 px-3 py-2 text-sm text-bad"
            >
              Failed to load job detail: {(detailQ.error as Error).message}
            </p>
          )}

          {d && (
            <div data-testid="job-detail">
              <p className="eyebrow mb-2">What this job did</p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                <Stat label="Documents" value={d.total_documents} />
                <Stat label="Chunks added" value={d.chunks_added} />
                <Stat label="Chunks removed" value={d.chunks_removed} />
                <Stat label="Duration" value={fmtDuration(d.execution_time_ms)} />
                {/* Index-wide chunk total AFTER this job — distinct from the
                    per-job add/remove deltas above. */}
                <Stat label="Index total" value={d.total_chunks} />
                {d.progress && (
                  <>
                    <Stat
                      label="Files"
                      value={`${d.progress.files_processed} / ${d.progress.files_total}`}
                    />
                    <Stat
                      label="Progress"
                      value={`${Math.round(d.progress_percent)}%`}
                    />
                  </>
                )}
              </div>

              {evictions.length > 0 && (
                <>
                  <p className="eyebrow mb-2 mt-5">Manifest changes</p>
                  <div className="grid grid-cols-3 gap-2">
                    {evictions.map(([k, v]) => (
                      <Stat key={k} label={k.replace(/_/g, " ")} value={v} />
                    ))}
                  </div>
                </>
              )}

              {fileLists.length > 0 && (
                <div data-testid="job-detail-files">
                  <p className="eyebrow mb-1 mt-5">Files</p>
                  {fileLists.map(([k, files]) => (
                    <FileList key={k} label={k} files={files} />
                  ))}
                </div>
              )}

              <p className="eyebrow mb-1 mt-5">Details</p>
              <div className="rounded-lg border border-line/60 bg-ink-700/20 px-3">
                <MetaRow label="Enqueued" value={fmtTime(d.enqueued_at, formatDateTime)} />
                <MetaRow label="Started" value={fmtTime(d.started_at, formatDateTime)} />
                <MetaRow label="Finished" value={fmtTime(d.finished_at, formatDateTime)} />
                {d.retry_count > 0 && (
                  <MetaRow label="Retries" value={String(d.retry_count)} />
                )}
                {d.budget_info &&
                  typeof d.budget_info.estimated_tokens === "number" &&
                  typeof d.budget_info.limit === "number" && (
                    <MetaRow
                      label="Budget"
                      value={`needs ~${d.budget_info.estimated_tokens.toLocaleString()} tokens (cap ${d.budget_info.limit.toLocaleString()})`}
                    />
                  )}
                {d.progress?.current_file && d.status === "running" && (
                  <MetaRow label="Current file" value={d.progress.current_file} />
                )}
              </div>

              {d.error && (
                <>
                  <p className="eyebrow mb-1 mt-5 text-bad">Error</p>
                  <pre className="overflow-auto whitespace-pre-wrap break-words rounded-lg border border-bad/30 bg-bad/10 p-3 font-mono text-xs text-bad">
                    {d.error}
                  </pre>
                </>
              )}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
