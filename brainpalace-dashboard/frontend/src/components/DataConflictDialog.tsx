import { AlertTriangle } from "lucide-react";
import type { DataConflictEnvelope } from "../api/types";

export function DataConflictDialog({
  conflict,
  busy,
  onReindex,
  onCancel,
}: {
  conflict: DataConflictEnvelope | null;
  busy: boolean;
  onReindex: () => void;
  onCancel: () => void;
}) {
  if (!conflict) return null;
  const { documents, chunks } = conflict.counts;
  return (
    <div
      role="alertdialog"
      data-testid="data-conflict-dialog"
      className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4"
    >
      <div className="panel max-w-lg p-6">
        <div className="mb-3 flex items-center gap-2 text-bad">
          <AlertTriangle className="h-5 w-5" aria-hidden="true" />
          <h2 className="font-display text-base font-semibold">
            Can&rsquo;t save — incompatible with indexed data
          </h2>
        </div>
        <p className="mb-3 text-sm text-fg-muted">
          {conflict.message}
          {documents != null && (
            <>
              {" "}
              ({documents} documents, {chunks} chunks already indexed.)
            </>
          )}
        </p>
        <ul className="mb-4 space-y-1 text-xs text-fg-faint">
          {conflict.fields.map((f) => (
            <li key={f.dotpath} data-testid={`conflict-field-${f.dotpath}`}>
              <code>{f.dotpath}</code>: {String(f.current)} &rarr; {String(f.new)}
            </li>
          ))}
        </ul>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            data-testid="conflict-cancel"
            onClick={onCancel}
            disabled={busy}
            className="btn-ghost btn-sm"
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid="conflict-reindex"
            onClick={onReindex}
            disabled={busy}
            className="btn-primary btn-sm"
          >
            Save &amp; reindex now
          </button>
        </div>
      </div>
    </div>
  );
}
