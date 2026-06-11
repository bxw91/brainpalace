import { useQuery } from "@tanstack/react-query";
import { getSessionArchive } from "../api/client";
import type { ArchivedSession } from "../api/types";
import { DataTable, type Column } from "./DataTable";
import { useDisplayFormat } from "../format/datetime";

const fmtBytes = (n: number) =>
  n >= 1024 * 1024 ? `${(n / (1024 * 1024)).toFixed(1)} MB` : `${(n / 1024).toFixed(1)} KB`;

/** Archived-session metadata list. Transcript content is never shown
 *  (raw archives can contain secrets) — this is an inventory, not a reader. */
export function SessionArchivePanel({ instanceId }: { instanceId: string }) {
  const { formatDateTime } = useDisplayFormat();
  const archiveQ = useQuery({
    queryKey: ["session-archive", instanceId],
    queryFn: () => getSessionArchive(instanceId),
    retry: false,
  });
  const data = archiveQ.data;
  if (!data) return null;

  const columns: Column<ArchivedSession>[] = [
    {
      key: "session_id",
      header: "Session",
      cell: (r) => (
        <span className="flex flex-col" title={r.archive_path}>
          <span className="text-xs text-fg">{r.title ?? "(untitled session)"}</span>
          <span className="font-mono text-[10px] text-fg-faint">{r.session_id}</span>
        </span>
      ),
      sortValue: (r) => r.title ?? r.session_id,
    },
    {
      key: "mtime",
      header: "Last activity",
      cell: (r) => (
        <span className="text-xs text-fg-muted">
          {formatDateTime(new Date(r.mtime * 1000))}
        </span>
      ),
      sortValue: (r) => r.mtime,
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

  return (
    <div data-testid="session-archive" className="panel flex flex-col gap-3 p-5">
      <p className="eyebrow">
        Archive — {data.archived_sessions} session
        {data.archived_sessions === 1 ? "" : "s"} ·{" "}
        {fmtBytes(data.archived_bytes)}
      </p>
      <DataTable<ArchivedSession>
        rows={data.sessions}
        columns={columns}
        rowKey={(r) => r.session_id}
        empty="No archived sessions yet."
      />
    </div>
  );
}
