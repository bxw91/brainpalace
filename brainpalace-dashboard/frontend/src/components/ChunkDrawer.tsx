import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { getDocumentChunks } from "../api/client";

/**
 * Right-side drawer showing every chunk of one indexed file: text plus the
 * metadata users need to spot junk (source_type, language, sizes).
 */
export function ChunkDrawer({
  instanceId,
  folder,
  path,
  onClose,
}: {
  instanceId: string;
  folder: string;
  path: string | null;
  onClose: () => void;
}) {
  const chunksQ = useQuery({
    queryKey: ["doc-chunks", instanceId, folder, path],
    queryFn: () => getDocumentChunks(instanceId, folder, path!),
    enabled: !!path,
    retry: false,
  });

  // Escape closes the drawer (same behavior as QueryDrawer).
  useEffect(() => {
    if (!path) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [path, onClose]);

  if (!path) return null;
  const data = chunksQ.data;

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
        aria-labelledby="h3-chunk-drawer-title"
        data-testid="chunk-drawer"
        className="panel animate-fade-up absolute right-0 top-0 flex h-full w-full max-w-2xl flex-col gap-3 overflow-y-auto rounded-none border-y-0 border-r-0 p-5"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="eyebrow">Chunks</p>
            <h3
              id="h3-chunk-drawer-title"
              className="truncate font-mono text-sm text-fg"
              title={path}
            >
              {path}
            </h3>
            {data && (
              <p className="mt-0.5 text-xs text-fg-faint">
                {data.total_chunks} chunk{data.total_chunks === 1 ? "" : "s"}{" "}
                indexed
                {data.chunks.length < data.total_chunks
                  ? ` · showing first ${data.chunks.length}`
                  : ""}
              </p>
            )}
          </div>
          <button
            type="button"
            data-testid="btn-chunk-drawer-close"
            onClick={onClose}
            aria-label="Close chunk drawer"
            className="text-fg-faint transition-colors hover:text-fg"
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>

        {chunksQ.isLoading && <p className="text-sm text-fg-faint">Loading…</p>}
        {chunksQ.isError && (
          <p className="text-sm text-warn">
            {(chunksQ.error as Error)?.message ?? "Failed to load chunks."}
          </p>
        )}
        {data?.chunks.map((c, i) => (
          <div
            key={c.chunk_id}
            data-testid={`chunk-${c.chunk_id}`}
            className="rounded-lg border border-line/60 bg-ink-700/30 p-3"
          >
            <p className="mb-2 flex flex-wrap items-center gap-1.5 text-[0.65rem]">
              <span className="font-mono text-fg-faint">#{i + 1}</span>
              {["source_type", "language"].map((k) =>
                c.metadata[k] ? (
                  <span
                    key={k}
                    className="rounded bg-ink-600 px-1.5 py-0.5 font-mono text-fg-muted"
                  >
                    {k}: {String(c.metadata[k])}
                  </span>
                ) : null,
              )}
              <span className="rounded bg-ink-600 px-1.5 py-0.5 font-mono text-fg-muted">
                {c.text.length} chars
              </span>
            </p>
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-xs text-fg-muted">
              {c.text}
            </pre>
          </div>
        ))}
      </aside>
    </div>
  );
}
