import { useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { Search, ChevronLeft, ChevronRight } from "lucide-react";
import { getFolders, getDocuments } from "../api/client";
import type { DocumentRow } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { ChunkDrawer } from "../components/ChunkDrawer";
import { useOptionalSelectedInstance } from "../state/selectedInstance";
import {
  NoInstance,
  StoppedState,
  ErrorState,
  TabSkeleton,
  isUnreachable,
} from "../components/TabState";

const PAGE_SIZE = 100;

const fmtBytes = (n: number) =>
  n >= 1024 * 1024
    ? `${(n / (1024 * 1024)).toFixed(1)} MB`
    : n >= 1024
      ? `${(n / 1024).toFixed(1)} KB`
      : `${n} B`;

export function Documents({ instanceId }: { instanceId?: string }) {
  const ctx = useOptionalSelectedInstance();
  const id = instanceId ?? ctx?.selectedId ?? null;

  const [folder, setFolder] = useState<string | null>(null);
  const [contains, setContains] = useState("");
  const [page, setPage] = useState(0);
  const [openPath, setOpenPath] = useState<string | null>(null);

  // Any change to the folder or the filter invalidates the current page number.
  const selectFolder = (f: string) => {
    setFolder(f);
    setPage(0);
  };
  const changeContains = (v: string) => {
    setContains(v);
    setPage(0);
  };

  const foldersQ = useQuery({
    queryKey: ["folders", id],
    queryFn: () => getFolders(id!),
    enabled: !!id,
    retry: false,
  });

  const activeFolder =
    folder ?? foldersQ.data?.folders[0]?.folder_path ?? null;

  const docsQ = useQuery({
    queryKey: ["documents", id, activeFolder, contains, page],
    queryFn: () =>
      getDocuments(id!, {
        folder: activeFolder!,
        ...(contains.trim() ? { contains: contains.trim() } : {}),
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      }),
    enabled: !!id && !!activeFolder,
    retry: false,
    // Keep the current page visible while the next one loads (no skeleton flash).
    placeholderData: keepPreviousData,
  });

  const total = docsQ.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const shownFrom = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const shownTo = page * PAGE_SIZE + (docsQ.data?.files.length ?? 0);
  const canPrev = page > 0;
  const canNext = shownTo < total;

  const columns: Column<DocumentRow>[] = [
    {
      key: "path",
      header: "File",
      cell: (r) => (
        <span className="block break-all font-mono text-xs" title={r.path}>
          {r.path}
        </span>
      ),
      sortValue: (r) => r.path,
    },
    {
      key: "chunks",
      header: "Chunks",
      align: "right",
      cell: (r) => <span className="tabular-nums">{r.chunk_count}</span>,
      sortValue: (r) => r.chunk_count,
    },
    {
      key: "size",
      header: "Size",
      align: "right",
      cell: (r) => (
        <span className="tabular-nums text-fg-muted">{fmtBytes(r.size_bytes)}</span>
      ),
      sortValue: (r) => r.size_bytes,
    },
  ];

  if (!id) {
    return (
      <NoInstance
        testId="tab-documents"
        message="Select an instance to browse its indexed documents."
      />
    );
  }
  if (isUnreachable(foldersQ.error) || isUnreachable(docsQ.error)) {
    return <StoppedState testId="documents-stopped" />;
  }
  if (foldersQ.isError || docsQ.isError) {
    const err = (foldersQ.error ?? docsQ.error) as Error;
    return (
      <ErrorState
        testId="documents-error"
        message={err?.message}
        onRetry={() => {
          foldersQ.refetch();
          docsQ.refetch();
        }}
        retrying={foldersQ.isFetching || docsQ.isFetching}
      />
    );
  }
  if (foldersQ.isLoading) {
    return (
      <div data-testid="tab-documents">
        <TabSkeleton rows={3} />
      </div>
    );
  }

  return (
    <div data-testid="tab-documents" className="flex flex-col gap-4">
      <div>
        <p className="eyebrow">Files</p>
        <h2 className="mt-0.5 font-display text-base font-semibold tracking-tight">
          Browse what's actually indexed, file by file
        </h2>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="select-doc-folder" className="sr-only">
          Folder
        </label>
        <select
          id="select-doc-folder"
          data-testid="select-doc-folder"
          value={activeFolder ?? ""}
          onChange={(e) => selectFolder(e.target.value)}
          className="max-w-md truncate rounded-lg border border-line bg-ink-700/50 px-3 py-1.5 text-sm text-fg focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
        >
          {(foldersQ.data?.folders ?? []).map((f) => (
            <option key={f.folder_path} value={f.folder_path}>
              {f.folder_path}
            </option>
          ))}
        </select>
        {docsQ.data && (
          <span className="text-xs text-fg-faint" data-testid="doc-count">
            {total.toLocaleString("en-US")} file{total === 1 ? "" : "s"}
            {contains.trim() ? " (filtered)" : ""}
          </span>
        )}
        <div className="relative ml-auto">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-faint"
            aria-hidden="true"
          />
          <label htmlFor="input-doc-contains" className="sr-only">
            Filter files
          </label>
          <input
            id="input-doc-contains"
            data-testid="input-doc-contains"
            type="text"
            value={contains}
            onChange={(e) => changeContains(e.target.value)}
            placeholder="Filter by filename or folder…"
            className="w-64 rounded-lg border border-line bg-ink-700/50 py-1.5 pl-9 pr-3 text-sm text-fg placeholder:text-fg-faint focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
          />
        </div>
      </div>

      <DataTable<DocumentRow>
        rows={docsQ.data?.files ?? []}
        columns={columns}
        rowKey={(r) => r.path}
        rowTestId={(r) => `doc-row-${r.path}`}
        onRowClick={(r) => setOpenPath(r.path)}
        empty="No indexed files in this folder."
      />

      {total > 0 && (
        <div
          data-testid="doc-pager"
          className="flex items-center justify-between gap-3 text-xs text-fg-muted"
        >
          <span className="tabular-nums">
            {shownFrom.toLocaleString("en-US")}–{shownTo.toLocaleString("en-US")} of{" "}
            {total.toLocaleString("en-US")}
          </span>
          <div className="flex items-center gap-2">
            <span className="tabular-nums text-fg-faint">
              Page {page + 1} of {pageCount.toLocaleString("en-US")}
            </span>
            <button
              type="button"
              data-testid="doc-prev"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={!canPrev}
              aria-label="Previous page"
              className="flex items-center gap-1 rounded-lg border border-line bg-ink-700/50 px-2.5 py-1 text-fg enabled:hover:border-accent/60 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              Prev
            </button>
            <button
              type="button"
              data-testid="doc-next"
              onClick={() => setPage((p) => p + 1)}
              disabled={!canNext}
              aria-label="Next page"
              className="flex items-center gap-1 rounded-lg border border-line bg-ink-700/50 px-2.5 py-1 text-fg enabled:hover:border-accent/60 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Next
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>
        </div>
      )}

      {activeFolder && (
        <ChunkDrawer
          instanceId={id}
          folder={activeFolder}
          path={openPath}
          onClose={() => setOpenPath(null)}
        />
      )}
    </div>
  );
}
