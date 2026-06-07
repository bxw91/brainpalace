import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderPlus, Trash2, RotateCcw, Eye, EyeOff } from "lucide-react";
import {
  getFolders,
  getJobs,
  removeFolder,
  addFolder,
  resetIndex,
} from "../api/client";
import type { FolderRow } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { FolderPicker, type AddFolderPayload } from "../components/FolderPicker";
import { JobProgress, isJobActive } from "../components/JobProgress";
import { useToast } from "../components/Toast";
import { useOptionalSelectedInstance } from "../state/selectedInstance";
import {
  NoInstance,
  StoppedState,
  ErrorState,
  TabSkeleton,
  isUnreachable,
} from "../components/TabState";

const fmt = (n: number) => n.toLocaleString("en-US");

function relTime(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const secs = Math.round((Date.now() - d.getTime()) / 1000);
  if (secs < 60) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export function Folders({ instanceId }: { instanceId?: string }) {
  const ctx = useOptionalSelectedInstance();
  const id = instanceId ?? ctx?.selectedId ?? null;
  const { toast } = useToast();
  const qc = useQueryClient();

  const [pickerOpen, setPickerOpen] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<string | null>(null);
  const [resetOpen, setResetOpen] = useState(false);

  const jobsQ = useQuery({
    queryKey: ["jobs", id],
    queryFn: () => getJobs(id!),
    enabled: !!id,
    retry: false,
    refetchInterval: (q) =>
      (q.state.data?.jobs ?? []).some(isJobActive) ? 1500 : false,
  });

  // While an index job is active, keep the folder list fresh so a newly
  // indexed folder appears as soon as its job finishes (without a manual reload).
  const jobActive = (jobsQ.data?.jobs ?? []).some(isJobActive);

  const foldersQ = useQuery({
    queryKey: ["folders", id],
    queryFn: () => getFolders(id!),
    enabled: !!id,
    retry: false,
    refetchInterval: jobActive ? 2000 : false,
  });

  // When the last active job finishes, do one final folder refetch so the just-
  // indexed folder appears immediately (the poll above stops once jobActive flips).
  const prevJobActive = useRef(jobActive);
  useEffect(() => {
    if (prevJobActive.current && !jobActive) {
      void foldersQ.refetch();
    }
    prevJobActive.current = jobActive;
  }, [jobActive, foldersQ]);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["folders", id] });
    qc.invalidateQueries({ queryKey: ["jobs", id] });
    qc.invalidateQueries({ queryKey: ["status", id] });
  };

  const addM = useMutation({
    mutationFn: (p: AddFolderPayload) => addFolder(id!, p),
    onSuccess: () => {
      setPickerOpen(false);
      toast("Folder queued for indexing.", "success");
      invalidate();
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Failed to add folder.", "error"),
  });

  const removeM = useMutation({
    mutationFn: (path: string) => removeFolder(id!, path),
    onSuccess: () => {
      setRemoveTarget(null);
      toast("Folder removed from the index.", "success");
      invalidate();
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Failed to remove folder.", "error"),
  });

  const resetM = useMutation({
    mutationFn: () => resetIndex(id!),
    onSuccess: () => {
      setResetOpen(false);
      toast("Index reset.", "success");
      invalidate();
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Failed to reset index.", "error"),
  });

  if (!id) {
    return (
      <NoInstance
        testId="tab-folders"
        message="Select an instance to manage its indexed folders."
      />
    );
  }

  if (isUnreachable(foldersQ.error)) {
    return <StoppedState testId="folders-stopped" />;
  }

  if (foldersQ.isError) {
    return (
      <ErrorState
        testId="folders-error"
        message={(foldersQ.error as Error)?.message}
        onRetry={() => foldersQ.refetch()}
        retrying={foldersQ.isFetching}
      />
    );
  }

  if (foldersQ.isLoading) {
    return (
      <div data-testid="tab-folders">
        <TabSkeleton rows={2} />
      </div>
    );
  }

  const folders = foldersQ.data?.folders ?? [];
  const jobs = jobsQ.data?.jobs ?? [];

  const columns: Column<FolderRow>[] = [
    {
      key: "path",
      header: "Folder",
      cell: (f) => (
        <span className="font-mono text-xs text-fg">{f.folder_path}</span>
      ),
      sortValue: (f) => f.folder_path,
    },
    {
      key: "chunks",
      header: "Chunks",
      align: "right",
      cell: (f) => <span className="tabular-nums">{fmt(f.chunk_count)}</span>,
      sortValue: (f) => f.chunk_count,
    },
    {
      key: "watch",
      header: "Watch",
      cell: (f) =>
        f.watch_mode === "auto" ? (
          <span className="inline-flex items-center gap-1.5 rounded-md bg-run/15 px-2 py-0.5 text-xs font-medium text-run">
            <Eye className="h-3 w-3" aria-hidden="true" /> auto
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 rounded-md bg-ink-600 px-2 py-0.5 text-xs font-medium text-fg-muted">
            <EyeOff className="h-3 w-3" aria-hidden="true" /> off
          </span>
        ),
      sortValue: (f) => f.watch_mode,
    },
    {
      key: "last",
      header: "Last indexed",
      cell: (f) => (
        <span className="text-xs text-fg-muted">{relTime(f.last_indexed)}</span>
      ),
      sortValue: (f) => f.last_indexed ?? "",
    },
  ];

  return (
    <div data-testid="tab-folders" className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="eyebrow">Indexed folders</p>
          <h2 className="mt-0.5 font-display text-base font-semibold tracking-tight">
            {folders.length} folder{folders.length === 1 ? "" : "s"}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="btn-add-folder"
            onClick={() => setPickerOpen(true)}
            className="btn-primary btn-sm"
          >
            <FolderPlus className="h-4 w-4" aria-hidden="true" /> Add folder
          </button>
          <button
            type="button"
            data-testid="btn-reset-index"
            onClick={() => setResetOpen(true)}
            className="btn-danger btn-sm"
          >
            <RotateCcw className="h-4 w-4" aria-hidden="true" /> Reset index
          </button>
        </div>
      </div>

      <JobProgress jobs={jobs} />

      <DataTable<FolderRow>
        rows={folders}
        columns={columns}
        rowKey={(f) => f.folder_path}
        rowTestId={(f) => `folder-row-${f.folder_path}`}
        empty="No folders indexed yet — add one to get started."
        trailing={{
          header: "",
          cell: (f) => (
            <button
              type="button"
              data-testid={`btn-remove-${f.folder_path}`}
              onClick={() => setRemoveTarget(f.folder_path)}
              className="btn-danger btn-sm"
              aria-label={`Remove ${f.folder_path}`}
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" /> Remove
            </button>
          ),
        }}
      />

      <FolderPicker
        open={pickerOpen}
        busy={addM.isPending}
        onAdd={(p) => addM.mutate(p)}
        onCancel={() => setPickerOpen(false)}
      />

      <ConfirmDialog
        open={removeTarget !== null}
        title="Remove folder from index?"
        message={
          <>
            This drops all chunks for{" "}
            <span className="font-mono text-fg">{removeTarget}</span>. The files
            on disk are untouched.
          </>
        }
        confirmLabel="Remove"
        tone="danger"
        busy={removeM.isPending}
        onConfirm={() => removeTarget && removeM.mutate(removeTarget)}
        onCancel={() => setRemoveTarget(null)}
      />

      <ConfirmDialog
        open={resetOpen}
        title="Reset the entire index?"
        message="This deletes ALL indexed chunks for every folder on this instance. You'll need to re-index from scratch."
        confirmLabel="Reset index"
        tone="danger"
        busy={resetM.isPending}
        onConfirm={() => resetM.mutate()}
        onCancel={() => setResetOpen(false)}
      />
    </div>
  );
}
