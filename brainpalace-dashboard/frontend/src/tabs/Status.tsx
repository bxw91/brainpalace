import { useQuery } from "@tanstack/react-query";
import { FileText, Boxes, FolderTree, Share2, GitCommit, AlertTriangle } from "lucide-react";
import { getInstanceStatus } from "../api/client";
import { StatCard } from "../components/StatCard";
import { useOptionalSelectedInstance } from "../state/selectedInstance";
import {
  NoInstance,
  StoppedState,
  ErrorState,
  TabSkeleton,
  isUnreachable,
} from "../components/TabState";

const fmt = (n: number) => n.toLocaleString("en-US");

function asArray(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}

function obj(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5">
      <span className="text-sm text-fg-muted">{label}</span>
      <span className="min-w-0 text-right text-sm text-fg">{value}</span>
    </div>
  );
}

// Row keys the web promotes to banners (they are ROWS in the shared server
// report, styled as banners here — a presentation choice on stable keys, the
// wording still comes entirely from the server).
const BANNER_KEYS = new Set(["read_only", "self_heal", "index_health"]);

const TONE: Record<string, string> = {
  default: "text-fg",
  good: "text-run",
  warn: "text-warn",
  bad: "text-bad",
  dim: "text-fg-muted",
  accent: "text-accent",
};

const ALERT_BORDER: Record<string, string> = {
  info: "border-accent/30 bg-accent/10 text-accent",
  warn: "border-warn/30 bg-warn/15 text-warn",
  bad: "border-bad/30 bg-bad/15 text-bad",
};

type ReportRow = { key: string; label: string; value: string; tone: string };
type ReportAlert = {
  kind: string;
  severity: string;
  title: string;
  lines: string[];
  action?: string | null;
};

/** Severity a toned ROW gets when promoted to a banner (no `severity` of its
 *  own — only `tone`). */
function bannerSeverity(tone: string): string {
  if (tone === "bad") return "bad";
  if (tone === "warn") return "warn";
  return "info";
}

/**
 * Per-instance "Status" — the full `brainpalace status` view for the SELECTED
 * instance. Distinct from the fleet-wide Overview tab. Rows and alerts are
 * rendered from the server's shared `report` (brainpalace_server/status_report.py)
 * — the same source `bp status` renders — so this tab can't drift from the CLI.
 */
export function Status({ instanceId }: { instanceId?: string }) {
  const ctx = useOptionalSelectedInstance();
  const id = instanceId ?? ctx?.selectedId ?? null;

  const statusQ = useQuery({
    queryKey: ["status", id],
    queryFn: () => getInstanceStatus(id!),
    enabled: !!id,
    retry: false,
    refetchInterval: 8000,
  });

  if (!id) {
    return (
      <NoInstance
        testId="tab-status"
        message="Select an instance to see its indexing status."
      />
    );
  }
  if (isUnreachable(statusQ.error)) return <StoppedState testId="status-stopped" />;
  if (statusQ.isError) {
    return (
      <ErrorState
        testId="status-error"
        message={(statusQ.error as Error)?.message}
        onRetry={() => statusQ.refetch()}
        retrying={statusQ.isFetching}
      />
    );
  }
  if (statusQ.isLoading || !statusQ.data) {
    return (
      <div data-testid="tab-status">
        <TabSkeleton rows={3} />
      </div>
    );
  }

  const s = statusQ.data;
  const features = obj(s.features);
  const git = obj(features.git_index);
  const num = (v: unknown): number => (typeof v === "number" ? v : 0);

  const folders = asArray(s.indexed_folders).map((f) =>
    typeof f === "string" ? f : String((obj(f).folder_path ?? obj(f).path) ?? f),
  );

  const report = (s.report ?? { rows: [], alerts: [] }) as {
    rows: ReportRow[];
    alerts: ReportAlert[];
  };
  const bannerRows = report.rows.filter((r) => BANNER_KEYS.has(r.key));
  const tableRows = report.rows.filter((r) => !BANNER_KEYS.has(r.key));

  return (
    <div data-testid="tab-status" className="flex flex-col gap-6">
      {report.alerts.map((alert) => (
        <div
          key={alert.kind}
          role="alert"
          className={`flex items-start gap-2 rounded-lg border px-4 py-3 text-sm ${
            ALERT_BORDER[alert.severity] ?? ALERT_BORDER.warn
          }`}
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div className="flex flex-col gap-1">
            <span className="font-semibold">{alert.title}</span>
            {alert.lines.map((line, i) => (
              <span key={i}>{line}</span>
            ))}
            {alert.action && (
              <code className="mt-1 w-fit rounded bg-ink-900/40 px-1 py-0.5 font-mono text-xs">
                {alert.action}
              </code>
            )}
          </div>
        </div>
      ))}
      {bannerRows.map((row) => (
        <div
          key={row.key}
          role="status"
          className={`flex items-start gap-2 rounded-lg border px-4 py-3 text-sm ${
            ALERT_BORDER[bannerSeverity(row.tone)]
          }`}
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <div className="flex flex-col gap-1">
            <span className="font-semibold">{row.label}</span>
            <span style={{ whiteSpace: "pre-line" }}>{row.value}</span>
          </div>
        </div>
      ))}

      {/* Headline cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          testId="stat-documents"
          label="Documents"
          value={fmt(num(s.total_documents))}
          hint={`${fmt(num(s.code_documents))} code · ${fmt(num(s.doc_documents))} docs`}
          tone="accent"
          icon={<FileText className="h-4 w-4" aria-hidden="true" />}
        />
        <StatCard
          testId="stat-chunks"
          label="Chunks"
          value={fmt(num(s.total_chunks))}
          hint={`${fmt(num(s.total_code_chunks))} code · ${fmt(num(s.total_doc_chunks))} docs`}
          tone="accent"
          icon={<Boxes className="h-4 w-4" aria-hidden="true" />}
        />
        <StatCard
          testId="stat-folders"
          label="Indexed folders"
          value={fmt(folders.length)}
          tone="default"
          icon={<FolderTree className="h-4 w-4" aria-hidden="true" />}
        />
        <StatCard
          testId="stat-git"
          label="Git commits"
          value={fmt(num(git.commit_count) || num(s.git_commits))}
          tone={git.enabled ? "default" : "idle"}
          icon={<GitCommit className="h-4 w-4" aria-hidden="true" />}
        />
      </div>

      {/* Full detail table — the shared server report, same source as `bp status`. */}
      <div className="panel p-6">
        <div className="mb-2 flex items-center gap-2">
          <Share2 className="h-4 w-4 text-accent" aria-hidden="true" />
          <h2 className="font-display text-base font-semibold tracking-tight">
            Server status
          </h2>
        </div>
        <div className="divide-y divide-line/60">
          {tableRows.map((row) => (
            <Row
              key={row.key}
              label={row.label}
              value={
                <span
                  className={TONE[row.tone] ?? "text-fg"}
                  style={{ whiteSpace: "pre-line" }}
                >
                  {row.value}
                </span>
              }
            />
          ))}
        </div>
      </div>
    </div>
  );
}
