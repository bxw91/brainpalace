import { useState } from "react";
import { useQueries, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  Brain,
  RefreshCw,
  Hammer,
  Trash2,
  EyeOff,
  Power,
} from "lucide-react";
import {
  getInstanceStatus,
  getMemories,
  memoryObsolete,
  memoryDelete,
  memoryRebuild,
  sessionsReindex,
} from "../api/client";
import type { MemoryRow } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/Toast";
import { SessionArchivePanel } from "../components/SessionArchivePanel";
import { DecisionTimeline } from "../components/DecisionTimeline";
import { MemoryComposer } from "../components/MemoryComposer";
import { useOptionalSelectedInstance } from "../state/selectedInstance";
import {
  NoInstance,
  StoppedState,
  ErrorState,
  TabSkeleton,
  isUnreachable,
} from "../components/TabState";

const fmt = (n: number) => n.toLocaleString("en-US");

function fmtBytes(b: number): string {
  if (b < 1024) return `${b} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = b / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(1)} ${units[i]}`;
}

type ArchiveInfo = {
  enabled?: boolean;
  retain_days?: number;
  archived_sessions?: number;
  archived_files?: number;
  archived_bytes?: number;
};
type MemoryInfo = {
  enabled?: boolean;
  session_chunks?: number;
  curated_memories?: number;
};
type ReconcilerInfo = {
  // The periodic reconcile sweep (server `session_memory.watcher_running`). It
  // copies live transcripts into the archive — so its running state belongs in
  // the archive card, not the index card.
  watcher_running?: boolean;
};

function Pill({ on }: { on: boolean }) {
  return on ? (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-run/15 px-2 py-0.5 text-xs font-medium text-run">
      <Power className="h-3 w-3" aria-hidden="true" /> on
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 rounded-md bg-ink-600 px-2 py-0.5 text-xs font-medium text-fg-muted">
      <Power className="h-3 w-3" aria-hidden="true" /> off
    </span>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between border-b border-line/40 py-1.5 last:border-0">
      <span className="text-sm text-fg-muted">{label}</span>
      <span className="font-mono text-sm tabular-nums text-fg">{value}</span>
    </div>
  );
}

export function Sessions({ instanceId }: { instanceId?: string }) {
  const ctx = useOptionalSelectedInstance();
  const id = instanceId ?? ctx?.selectedId ?? null;
  const { toast } = useToast();
  const qc = useQueryClient();

  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [obsoleteTarget, setObsoleteTarget] = useState<string | null>(null);
  const [rebuildOpen, setRebuildOpen] = useState(false);
  const [reindexOpen, setReindexOpen] = useState(false);

  const [statusQ, memoriesQ] = useQueries({
    queries: [
      {
        queryKey: ["status", id],
        queryFn: () => getInstanceStatus(id!),
        enabled: !!id,
        retry: false,
      },
      {
        queryKey: ["memories", id],
        queryFn: () => getMemories(id!),
        enabled: !!id,
        retry: false,
      },
    ],
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["memories", id] });
    qc.invalidateQueries({ queryKey: ["status", id] });
    qc.invalidateQueries({ queryKey: ["jobs", id] });
  };

  const obsoleteM = useMutation({
    mutationFn: (mid: string) => memoryObsolete(id!, mid),
    onSuccess: () => {
      setObsoleteTarget(null);
      toast("Memory marked obsolete.", "success");
      invalidate();
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Failed to obsolete memory.", "error"),
  });
  const deleteM = useMutation({
    mutationFn: (mid: string) => memoryDelete(id!, mid),
    onSuccess: () => {
      setDeleteTarget(null);
      toast("Memory deleted.", "success");
      invalidate();
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Failed to delete memory.", "error"),
  });
  const rebuildM = useMutation({
    mutationFn: () => memoryRebuild(id!),
    onSuccess: () => {
      setRebuildOpen(false);
      toast("Memory shadow index rebuilt.", "success");
      invalidate();
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Failed to rebuild index.", "error"),
  });
  const reindexM = useMutation({
    mutationFn: () => sessionsReindex(id!),
    onSuccess: () => {
      setReindexOpen(false);
      toast("Transcript re-index started.", "success");
      invalidate();
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Failed to re-index transcripts.", "error"),
  });

  if (!id) {
    return <NoInstance testId="tab-sessions" message="Select an instance to manage session memory." />;
  }
  if (isUnreachable(statusQ.error) || isUnreachable(memoriesQ.error)) {
    return <StoppedState testId="sessions-stopped" />;
  }
  if (statusQ.isError || memoriesQ.isError) {
    const err = (statusQ.error ?? memoriesQ.error) as Error | undefined;
    return (
      <ErrorState
        testId="sessions-error"
        message={err?.message}
        onRetry={() => {
          void statusQ.refetch();
          void memoriesQ.refetch();
        }}
        retrying={statusQ.isFetching || memoriesQ.isFetching}
      />
    );
  }
  if (statusQ.isLoading || memoriesQ.isLoading || !statusQ.data) {
    return (
      <div data-testid="tab-sessions">
        <TabSkeleton rows={2} />
      </div>
    );
  }

  const features = (statusQ.data.features ?? {}) as Record<string, unknown>;
  const archive = (features.session_archive ?? {}) as ArchiveInfo;
  const mem = (features.session_memory ?? {}) as MemoryInfo;
  // The reconcile sweep's running state is reported under session_memory for
  // back-compat, but it primarily drives the archive copy — surface it there.
  const reconciler = (features.session_memory ?? {}) as ReconcilerInfo;
  const memories = memoriesQ.data?.memories ?? [];

  const columns: Column<MemoryRow>[] = [
    {
      key: "content",
      header: "Memory",
      cell: (m) => (
        <span className={`text-sm ${m.obsolete ? "text-fg-faint line-through" : "text-fg"}`}>
          {m.content ?? "(empty)"}
        </span>
      ),
      sortValue: (m) => m.content ?? "",
    },
    {
      key: "category",
      header: "Category",
      cell: (m) =>
        m.category ? (
          <span className="rounded-md bg-ink-600 px-2 py-0.5 font-mono text-[0.66rem] uppercase tracking-wider text-fg-muted">
            {m.category}
          </span>
        ) : (
          <span className="text-fg-faint">—</span>
        ),
      sortValue: (m) => m.category ?? "",
    },
  ];

  return (
    <div data-testid="tab-sessions" className="flex flex-col gap-6">
      <div className="grid gap-4 lg:grid-cols-2">
        <div data-testid="card-session-archive" className="panel p-5">
          <div className="mb-3 flex items-center justify-between">
            <span className="flex items-center gap-2">
              <Archive className="h-4 w-4 text-accent" aria-hidden="true" />
              <span className="font-display text-sm font-semibold tracking-tight">
                Session archive
              </span>
            </span>
            <Pill on={!!archive.enabled} />
          </div>
          <Row
            label="Copy sweep"
            value={reconciler.watcher_running ? "running" : "idle"}
          />
          <Row label="Archived files" value={fmt(archive.archived_files ?? 0)} />
          <Row label="Archived sessions" value={fmt(archive.archived_sessions ?? 0)} />
          <Row label="On-disk size" value={fmtBytes(archive.archived_bytes ?? 0)} />
          <Row
            label="Retention"
            value={
              (archive.retain_days ?? 0) <= 0
                ? "forever"
                : `${archive.retain_days} days`
            }
          />
        </div>

        <div data-testid="card-session-index" className="panel p-5">
          <div className="mb-3 flex items-center justify-between">
            <span className="flex items-center gap-2">
              <Brain className="h-4 w-4 text-accent" aria-hidden="true" />
              <span className="font-display text-sm font-semibold tracking-tight">
                Session summarization &amp; indexing
              </span>
            </span>
            <Pill on={!!mem.enabled} />
          </div>
          <Row label="Session chunks" value={fmt(mem.session_chunks ?? 0)} />
          <Row label="Curated memories" value={fmt(mem.curated_memories ?? memories.length)} />
        </div>
      </div>

      <MemoryComposer instanceId={id} />

      <div className="flex items-center justify-between">
        <div>
          <p className="eyebrow">Curated memories</p>
          <h2 className="mt-0.5 font-display text-base font-semibold tracking-tight">
            {memories.length} memor{memories.length === 1 ? "y" : "ies"}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="btn-rebuild-memories"
            onClick={() => setRebuildOpen(true)}
            className="btn-ghost btn-sm"
          >
            <Hammer className="h-4 w-4" aria-hidden="true" /> Rebuild shadow index
          </button>
          <button
            type="button"
            data-testid="btn-sessions-reindex"
            onClick={() => setReindexOpen(true)}
            className="btn-ghost btn-sm"
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" /> Re-index transcripts
          </button>
        </div>
      </div>

      <DataTable<MemoryRow>
        rows={memories}
        columns={columns}
        rowKey={(m) => m.id}
        rowTestId={(m) => `memory-row-${m.id}`}
        empty="No curated memories yet."
        trailing={{
          header: "",
          cell: (m) => (
            <div className="flex justify-end gap-2">
              <button
                type="button"
                data-testid={`btn-obsolete-${m.id}`}
                onClick={() => setObsoleteTarget(m.id)}
                className="btn-ghost btn-sm"
              >
                <EyeOff className="h-3.5 w-3.5" aria-hidden="true" /> Obsolete
              </button>
              <button
                type="button"
                data-testid={`btn-delete-${m.id}`}
                onClick={() => setDeleteTarget(m.id)}
                className="btn-danger btn-sm"
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Delete
              </button>
            </div>
          ),
        }}
      />

      <SessionArchivePanel instanceId={id} />
      <DecisionTimeline instanceId={id} />

      <ConfirmDialog
        open={obsoleteTarget !== null}
        title="Mark memory obsolete?"
        message="Flags the curated memory as obsolete so it stops surfacing in recall. It is not deleted."
        confirmLabel="Mark obsolete"
        tone="default"
        busy={obsoleteM.isPending}
        onConfirm={() => obsoleteTarget && obsoleteM.mutate(obsoleteTarget)}
        onCancel={() => setObsoleteTarget(null)}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete this memory?"
        message="Permanently removes the curated memory. This cannot be undone."
        confirmLabel="Delete"
        tone="danger"
        busy={deleteM.isPending}
        onConfirm={() => deleteTarget && deleteM.mutate(deleteTarget)}
        onCancel={() => setDeleteTarget(null)}
      />

      <ConfirmDialog
        open={rebuildOpen}
        title="Rebuild the memory shadow index?"
        message="Re-embeds all curated memories into the searchable shadow index. Safe but may incur provider cost."
        confirmLabel="Rebuild"
        tone="default"
        busy={rebuildM.isPending}
        onConfirm={() => rebuildM.mutate()}
        onCancel={() => setRebuildOpen(false)}
      />

      <ConfirmDialog
        open={reindexOpen}
        title="Re-index session transcripts?"
        message="Re-embeds archived transcripts into the session index. This runs as a background job and may incur provider cost."
        confirmLabel="Re-index"
        tone="default"
        busy={reindexM.isPending}
        onConfirm={() => reindexM.mutate()}
        onCancel={() => setReindexOpen(false)}
      />
    </div>
  );
}
