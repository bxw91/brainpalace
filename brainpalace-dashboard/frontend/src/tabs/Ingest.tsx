import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, ChevronLeft, ChevronRight } from "lucide-react";
import { getIngestSources } from "../api/client";
import type { IngestSourceRow } from "../api/types";
import { DataTable, type Column } from "../components/DataTable";
import { IngestChunkDrawer } from "../components/IngestChunkDrawer";
import { useOptionalSelectedInstance } from "../state/selectedInstance";
import {
  NoInstance,
  StoppedState,
  ErrorState,
  TabSkeleton,
  isUnreachable,
} from "../components/TabState";

const PAGE_SIZE = 100;

const fmtWhen = (s: string | null) => {
  if (!s) return "—";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString("en-US");
};

export function Ingest({ instanceId }: { instanceId?: string }) {
  const ctx = useOptionalSelectedInstance();
  const id = instanceId ?? ctx?.selectedId ?? null;

  const [contains, setContains] = useState("");
  const [page, setPage] = useState(0);
  const [openSource, setOpenSource] = useState<string | null>(null);

  const changeContains = (v: string) => {
    setContains(v);
    setPage(0);
  };

  // The server returns all ingested sources at once (no server pagination), so
  // filtering + paging happen client-side over the fetched list.
  const sourcesQ = useQuery({
    queryKey: ["ingest-sources", id],
    queryFn: () => getIngestSources(id!),
    enabled: !!id,
    retry: false,
  });

  const filtered = useMemo(() => {
    const all = sourcesQ.data?.sources ?? [];
    const q = contains.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (s) =>
        s.source_id.toLowerCase().includes(q) ||
        s.domain.toLowerCase().includes(q) ||
        s.source.toLowerCase().includes(q),
    );
  }, [sourcesQ.data, contains]);

  const total = filtered.length;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageRows = filtered.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);
  const shownFrom = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const shownTo = page * PAGE_SIZE + pageRows.length;
  const canPrev = page > 0;
  const canNext = shownTo < total;

  const columns: Column<IngestSourceRow>[] = [
    {
      key: "source_id",
      header: "Source ID",
      cell: (r) => (
        <span className="block break-all font-mono text-xs" title={r.source_id}>
          {r.source_id}
        </span>
      ),
      sortValue: (r) => r.source_id,
    },
    {
      key: "domain",
      header: "Domain",
      cell: (r) => <span className="text-fg-muted">{r.domain || "—"}</span>,
      sortValue: (r) => r.domain,
    },
    {
      key: "source",
      header: "Source",
      cell: (r) => <span className="text-fg-muted">{r.source || "—"}</span>,
      sortValue: (r) => r.source,
    },
    {
      key: "chunks",
      header: "Chunks",
      align: "right",
      cell: (r) => <span className="tabular-nums">{r.chunk_count}</span>,
      sortValue: (r) => r.chunk_count,
    },
    {
      key: "ingested_at",
      header: "Ingested",
      align: "right",
      cell: (r) => (
        <span className="tabular-nums text-fg-muted">{fmtWhen(r.ingested_at)}</span>
      ),
      sortValue: (r) => r.ingested_at ?? "",
    },
  ];

  if (!id) {
    return (
      <NoInstance
        testId="tab-ingest"
        message="Select an instance to browse its ingested sources."
      />
    );
  }
  if (isUnreachable(sourcesQ.error)) {
    return <StoppedState testId="ingest-stopped" />;
  }
  if (sourcesQ.isError) {
    return (
      <ErrorState
        testId="ingest-error"
        message={(sourcesQ.error as Error)?.message}
        onRetry={() => sourcesQ.refetch()}
        retrying={sourcesQ.isFetching}
      />
    );
  }
  if (sourcesQ.isLoading) {
    return (
      <div data-testid="tab-ingest">
        <TabSkeleton rows={3} />
      </div>
    );
  }

  return (
    <div data-testid="tab-ingest" className="flex flex-col gap-4">
      <div>
        <p className="eyebrow">Ingested text</p>
        <h2 className="mt-0.5 font-display text-base font-semibold tracking-tight">
          Free text pushed in via <span className="font-mono">brainpalace ingest</span>
        </h2>
        <p className="mt-1 text-xs text-fg-faint">
          Programmatically-ingested sources, grouped by <code>source_id</code>. Writing
          and deleting stay on the CLI (<span className="font-mono">ingest</span> /{" "}
          <span className="font-mono">ingest --delete</span>); this view is read-only.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-fg-faint" data-testid="ingest-count">
          {total.toLocaleString("en-US")} source{total === 1 ? "" : "s"}
          {contains.trim() ? " (filtered)" : ""}
        </span>
        <div className="relative ml-auto">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-faint"
            aria-hidden="true"
          />
          <label htmlFor="input-ingest-contains" className="sr-only">
            Filter sources
          </label>
          <input
            id="input-ingest-contains"
            data-testid="input-ingest-contains"
            type="text"
            value={contains}
            onChange={(e) => changeContains(e.target.value)}
            placeholder="Filter by source_id, domain or source…"
            className="w-72 rounded-lg border border-line bg-ink-700/50 py-1.5 pl-9 pr-3 text-sm text-fg placeholder:text-fg-faint focus:border-accent/60 focus:outline-none focus:ring-2 focus:ring-accent/30"
          />
        </div>
      </div>

      <DataTable<IngestSourceRow>
        rows={pageRows}
        columns={columns}
        rowKey={(r) => r.source_id}
        rowTestId={(r) => `ingest-row-${r.source_id}`}
        onRowClick={(r) => setOpenSource(r.source_id)}
        empty="No ingested sources. Push text in with `brainpalace ingest FILE --domain … --source … --source-id …`."
      />

      {total > 0 && (
        <div
          data-testid="ingest-pager"
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
              data-testid="ingest-prev"
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
              data-testid="ingest-next"
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

      <IngestChunkDrawer
        instanceId={id}
        sourceId={openSource}
        onClose={() => setOpenSource(null)}
      />
    </div>
  );
}
