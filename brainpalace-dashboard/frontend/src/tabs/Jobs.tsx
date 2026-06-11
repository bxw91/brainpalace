import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Ban } from "lucide-react";
import { getJobs, cancelJob } from "../api/client";
import type { JobRow } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { JobDrawer } from "../components/JobDrawer";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { isJobActive } from "../components/JobProgress";
import { useToast } from "../components/Toast";
import { useOptionalSelectedInstance } from "../state/selectedInstance";
import { useDisplayFormat } from "../format/datetime";
import {
  NoInstance,
  StoppedState,
  ErrorState,
  TabSkeleton,
  isUnreachable,
} from "../components/TabState";

const STATUS_TONE: Record<string, string> = {
  running: "bg-accent/15 text-accent",
  queued: "bg-warn/15 text-warn",
  pending: "bg-warn/15 text-warn",
  done: "bg-run/15 text-run",
  error: "bg-bad/15 text-bad",
  cancelled: "bg-ink-600 text-fg-muted",
};

function fmtTime(iso: string | null, formatTime: (d: Date) => string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : formatTime(d);
}

/** Elapsed ms between started/finished (live to now while still running). */
function durationMs(j: JobRow): number | null {
  if (!j.started_at) return null;
  const start = new Date(j.started_at).getTime();
  if (Number.isNaN(start)) return null;
  const end = j.finished_at ? new Date(j.finished_at).getTime() : Date.now();
  if (Number.isNaN(end)) return null;
  return Math.max(0, end - start);
}

function fmtDuration(ms: number | null): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s % 60)}s`;
}

export function Jobs({ instanceId }: { instanceId?: string }) {
  const ctx = useOptionalSelectedInstance();
  const id = instanceId ?? ctx?.selectedId ?? null;
  const { toast } = useToast();
  const qc = useQueryClient();
  const [cancelTarget, setCancelTarget] = useState<string | null>(null);
  const [openJobId, setOpenJobId] = useState<string | null>(null);
  const { formatTime } = useDisplayFormat();

  const jobsQ = useQuery({
    queryKey: ["jobs", id],
    queryFn: () => getJobs(id!),
    enabled: !!id,
    retry: false,
    refetchInterval: (q) =>
      (q.state.data?.jobs ?? []).some(isJobActive) ? 2000 : false,
  });

  const cancelM = useMutation({
    mutationFn: (jobId: string) => cancelJob(id!, jobId),
    onSuccess: () => {
      setCancelTarget(null);
      toast("Job cancelled.", "success");
      qc.invalidateQueries({ queryKey: ["jobs", id] });
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Failed to cancel job.", "error"),
  });

  if (!id) {
    return <NoInstance testId="tab-jobs" message="Select an instance to see its indexing jobs." />;
  }
  if (isUnreachable(jobsQ.error)) {
    return <StoppedState testId="jobs-stopped" />;
  }
  if (jobsQ.isError) {
    return (
      <ErrorState
        testId="jobs-error"
        message={(jobsQ.error as Error)?.message}
        onRetry={() => jobsQ.refetch()}
        retrying={jobsQ.isFetching}
      />
    );
  }
  if (jobsQ.isLoading) {
    return (
      <div data-testid="tab-jobs">
        <TabSkeleton rows={2} />
      </div>
    );
  }

  const jobs = jobsQ.data?.jobs ?? [];

  const columns: Column<JobRow>[] = [
    {
      key: "id",
      header: "Job",
      cell: (j) => <span className="font-mono text-xs text-fg">{j.id}</span>,
      sortValue: (j) => j.id,
    },
    {
      key: "operation",
      header: "Type",
      cell: (j) => <span className="text-fg-muted">{j.operation}</span>,
      sortValue: (j) => j.operation,
    },
    {
      // Status + progress merged: the badge alone for finished jobs (their
      // progress is always 100%/empty — dead weight), plus an inline bar only
      // while the job is still active.
      key: "status",
      header: "Status",
      cell: (j) => {
        const pct = Math.round(j.progress_percent ?? 0);
        return (
          <div className="flex items-center gap-2">
            <span
              className={`rounded-md px-2 py-0.5 font-mono text-[0.66rem] uppercase tracking-wider ${STATUS_TONE[j.status] ?? "bg-ink-600 text-fg-muted"}`}
            >
              {j.status}
            </span>
            {isJobActive(j) && (
              <span className="flex items-center gap-1.5">
                <div className="h-1.5 w-16 overflow-hidden rounded-full bg-ink-600">
                  <div
                    className="h-full rounded-full bg-accent"
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="font-mono text-[0.66rem] tabular-nums text-fg-faint">
                  {pct}%
                </span>
              </span>
            )}
          </div>
        );
      },
      sortValue: (j) => j.status,
    },
    {
      key: "chunks_added",
      header: "+Chunks",
      align: "right",
      cell: (j) =>
        j.chunks_added > 0 ? (
          <span className="font-mono text-xs tabular-nums text-run">
            +{j.chunks_added}
          </span>
        ) : (
          <span className="text-fg-faint">—</span>
        ),
      sortValue: (j) => j.chunks_added ?? 0,
    },
    {
      key: "chunks_removed",
      header: "−Chunks",
      align: "right",
      cell: (j) =>
        j.chunks_removed > 0 ? (
          <span className="font-mono text-xs tabular-nums text-bad">
            −{j.chunks_removed}
          </span>
        ) : (
          <span className="text-fg-faint">—</span>
        ),
      sortValue: (j) => j.chunks_removed ?? 0,
    },
    {
      key: "started",
      header: "Started",
      cell: (j) => (
        <span className="text-xs text-fg-muted">{fmtTime(j.started_at, formatTime)}</span>
      ),
      sortValue: (j) => j.started_at ?? "",
    },
    {
      key: "duration",
      header: "Duration",
      align: "right",
      cell: (j) => (
        <span className="font-mono text-xs tabular-nums text-fg-muted">
          {fmtDuration(durationMs(j))}
        </span>
      ),
      sortValue: (j) => durationMs(j) ?? 0,
    },
    {
      key: "error",
      header: "Error",
      cell: (j) =>
        j.error ? (
          <span className="font-mono text-xs text-bad" title={j.error}>
            {j.error}
          </span>
        ) : (
          <span className="text-fg-faint">—</span>
        ),
    },
  ];

  return (
    <div data-testid="tab-jobs" className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <div>
          <p className="eyebrow">Indexing jobs</p>
          <h2 className="mt-0.5 font-display text-base font-semibold tracking-tight">
            {jobs.length} job{jobs.length === 1 ? "" : "s"}
          </h2>
        </div>
        {jobs.some(isJobActive) && (
          <span className="flex items-center gap-2 font-mono text-[0.68rem] uppercase tracking-wider text-accent">
            <span className="h-2 w-2 animate-pulse-dot rounded-full bg-accent" aria-hidden="true" />
            live
          </span>
        )}
      </div>

      <DataTable<JobRow>
        rows={jobs}
        columns={columns}
        rowKey={(j) => j.id}
        rowTestId={(j) => `job-row-${j.id}`}
        onRowClick={(j) => setOpenJobId(j.id)}
        empty="No indexing jobs yet."
        trailing={{
          header: "Actions",
          cell: (j) =>
            isJobActive(j) ? (
              <button
                type="button"
                data-testid={`btn-cancel-${j.id}`}
                onClick={(e) => {
                  e.stopPropagation();
                  setCancelTarget(j.id);
                }}
                className="btn-danger btn-sm"
              >
                <Ban className="h-3.5 w-3.5" aria-hidden="true" /> Cancel
              </button>
            ) : (
              <span className="text-fg-faint">—</span>
            ),
        }}
      />

      <ConfirmDialog
        open={cancelTarget !== null}
        title="Cancel this job?"
        message={
          <>
            Stop job <span className="font-mono text-fg">{cancelTarget}</span>.
            Any partial progress is kept; you can re-index later.
          </>
        }
        confirmLabel="Cancel job"
        tone="danger"
        busy={cancelM.isPending}
        onConfirm={() => cancelTarget && cancelM.mutate(cancelTarget)}
        onCancel={() => setCancelTarget(null)}
      />

      <JobDrawer instanceId={id} jobId={openJobId} onClose={() => setOpenJobId(null)} />
    </div>
  );
}
