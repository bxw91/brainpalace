import { useQuery } from "@tanstack/react-query";
import { FileText, Boxes, FolderTree, Share2, GitCommit, Lock } from "lucide-react";
import {
  getInstanceStatus,
  getInstanceHealth,
  getConfig,
  getSettings,
} from "../api/client";
import { StatCard } from "../components/StatCard";
import { useOptionalSelectedInstance } from "../state/selectedInstance";
import { useDisplayFormat } from "../format/datetime";
import {
  NoInstance,
  StoppedState,
  ErrorState,
  TabSkeleton,
  isUnreachable,
} from "../components/TabState";

const fmt = (n: number) => n.toLocaleString("en-US");

function fmtBytes(n: number): string {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), u.length - 1);
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`;
}

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

/**
 * Per-instance "Status" — the full `brainpalace status` view for the SELECTED
 * instance. Distinct from the fleet-wide Overview tab.
 */
export function Status({ instanceId }: { instanceId?: string }) {
  const ctx = useOptionalSelectedInstance();
  const id = instanceId ?? ctx?.selectedId ?? null;
  const { formatDateTime } = useDisplayFormat();

  const statusQ = useQuery({
    queryKey: ["status", id],
    queryFn: () => getInstanceStatus(id!),
    enabled: !!id,
    retry: false,
    refetchInterval: 8000,
  });
  // Best-effort extras (version, bm25) — never block the page.
  const healthQ = useQuery({
    queryKey: ["health", id],
    queryFn: () => getInstanceHealth(id!),
    enabled: !!id,
    retry: false,
  });
  const configQ = useQuery({
    queryKey: ["config", id],
    queryFn: () => getConfig(id!),
    enabled: !!id,
    retry: false,
  });
  // Control-plane (dashboard's own) version — fleet-wide, not per-instance.
  const settingsQ = useQuery({
    queryKey: ["dashboard-settings"],
    queryFn: getSettings,
    retry: false,
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
  const graph = obj(features.graph_index ?? s.graph_index);
  const cache = obj(s.embedding_cache);
  const watcher = obj(features.file_watcher ?? s.file_watcher);
  const archive = obj(features.session_archive);
  const memory = obj(features.session_memory);
  const extraction = obj(features.session_extraction);
  const lsp = obj(features.lsp);
  const git = obj(features.git_index);
  const cfg = obj(configQ.data);
  const bm25 = obj(cfg.bm25);

  const folders = asArray(s.indexed_folders).map((f) =>
    typeof f === "string" ? f : String((obj(f).folder_path ?? obj(f).path) ?? f),
  );
  const indexing = s.indexing_in_progress
    ? `In progress${
        typeof s.progress_percent === "number"
          ? ` — ${Math.round(s.progress_percent)}%`
          : ""
      }`
    : "Idle";
  const num = (v: unknown): number => (typeof v === "number" ? v : 0);
  const hitRate =
    typeof cache.hit_rate === "number"
      ? `${(cache.hit_rate * 100).toFixed(1)}%`
      : "—";

  // Read-only mode + self-heal + index-health — mirror `brainpalace status`.
  const readOnly = features.read_only === true;
  const heal = obj(obj(features.self_heal).last);
  const hasHeal =
    heal.error != null || heal.incomplete_reason != null || heal.restored != null;
  const healReadOnlySkip = heal.incomplete_reason === "read-only mode";
  const healIncomplete = !!heal.error || (!!heal.incomplete_reason && !healReadOnlySkip);
  const indexHealth = obj(features.index_health);
  const healEvents = num(indexHealth.heal_events);
  const healDropped = num(indexHealth.total_dropped);

  return (
    <div data-testid="tab-status" className="flex flex-col gap-6">
      {readOnly && (
        <div
          data-testid="readonly-banner"
          role="status"
          className="flex items-start gap-2 rounded-lg border border-warn/30 bg-warn/15 px-4 py-3 text-sm text-warn"
        >
          <Lock className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>
            <span className="font-semibold">Read-only mode is ON.</span> Provider calls
            are disabled (embedding, summarization, remote rerank); indexing jobs are
            skipped and self-heal will not delete; vector/hybrid queries fall back to
            BM25. Toggle with{" "}
            <code className="rounded bg-ink-900/40 px-1 py-0.5 font-mono text-xs">
              brainpalace read-only off
            </code>{" "}
            (restart to apply).
          </span>
        </div>
      )}
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

      {/* Full detail table — mirrors `brainpalace status`. */}
      <div className="panel p-6">
        <div className="mb-2 flex items-center gap-2">
          <Share2 className="h-4 w-4 text-accent" aria-hidden="true" />
          <h2 className="font-display text-base font-semibold tracking-tight">
            Server status
          </h2>
        </div>
        <div className="divide-y divide-line/60">
          <Row label="Server version" value={healthQ.data?.version ?? "—"} />
          <Row
            label="Dashboard version (control plane)"
            value={settingsQ.data?.version ?? "—"}
          />
          <Row label="Indexing" value={indexing} />
          <Row
            label="Indexed folders"
            value={
              folders.length === 0 ? (
                "none"
              ) : (
                <span className="flex flex-col items-end gap-0.5 font-mono text-xs">
                  {folders.map((f) => (
                    <span key={f} className="truncate">
                      {f}
                    </span>
                  ))}
                </span>
              )
            }
          />
          <Row
            label="Last indexed"
            value={
              s.last_indexed_at
                ? formatDateTime(new Date(s.last_indexed_at))
                : "never"
            }
          />
          <Row
            label="File watcher"
            value={
              watcher.enabled || watcher.running
                ? `running (${fmt(num(watcher.watched_folders))} folder(s))`
                : "stopped"
            }
          />
          <Row
            label="Session archive"
            value={
              archive.enabled
                ? `on — ${fmt(num(archive.archived_files))} files, ${fmtBytes(
                    num(archive.archived_bytes),
                  )} (${num(archive.retain_days) > 0 ? `${num(archive.retain_days)}d` : "forever"})`
                : "off"
            }
          />
          <Row
            label="Session memory"
            value={
              memory.enabled
                ? `on — ${fmt(num(memory.session_chunks))} chunks, ${fmt(
                    num(memory.curated_memories),
                  )} memories`
                : "off"
            }
          />
          <Row
            label="Session summarization"
            value={
              extraction.mode && extraction.mode !== "off"
                ? String(extraction.mode)
                : "off"
            }
          />
          <Row
            label="Embedding cache"
            value={`${fmt(num(cache.entry_count))} entries, ${hitRate} hit rate (${fmt(
              num(cache.hits),
            )} hits, ${fmt(num(cache.misses))} misses)`}
          />
          <Row
            label="Graph index"
            value={
              graph.enabled
                ? `enabled (${graph.store_type ?? "—"}) — ${fmt(
                    num(graph.entity_count),
                  )} entities, ${fmt(num(graph.relationship_count))} rels`
                : "disabled"
            }
          />
          <Row
            label="LSP"
            value={
              lsp.enabled
                ? `enabled (${asArray(lsp.languages).join(", ") || "—"})`
                : "disabled"
            }
          />
          <Row
            label="Git index"
            value={
              git.enabled
                ? `on — ${fmt(num(git.commit_count))} commits`
                : "off"
            }
          />
          {healEvents > 0 && healDropped > 0 && (
            <Row
              label="Index health"
              value={
                <span className="text-warn">
                  ⚠ {fmt(healEvents)} heal event(s), ~{fmt(healDropped)} vectors shed —
                  re-index to recover
                </span>
              }
            />
          )}
          {readOnly && (
            <Row
              label="Read-only"
              value={
                <span className="text-warn">
                  ON — provider calls disabled (embedding/summarization/remote-rerank
                  off; vector queries → BM25; indexing skipped)
                </span>
              }
            />
          )}
          {hasHeal && (
            <Row
              label="Self-heal"
              value={
                healIncomplete ? (
                  <span className="text-bad">
                    ⚠ incomplete — restored {fmt(num(heal.restored))}/
                    {fmt(num(heal.recoverable))}; stage 2 skipped to protect data — fix
                    + restart
                  </span>
                ) : healReadOnlySkip ? (
                  <span className="text-warn">
                    recovered {fmt(num(heal.restored))}/{fmt(num(heal.recoverable))}{" "}
                    chunk(s) from cache+dead (no re-embed); stage 2 skipped — read-only
                    (no deletes)
                  </span>
                ) : (
                  <span className="text-run">
                    restored {fmt(num(heal.restored))} chunk(s) from cache+dead (no
                    re-embed); {fmt(num(heal.files_dropped))} file(s) re-indexing (
                    {fmt(num(heal.residue))} chunk(s) need re-embed)
                  </span>
                )
              }
            />
          )}
          <Row
            label="BM25 language"
            value={`${bm25.language ?? "en"} (engine: ${bm25.engine ?? "stem"})`}
          />
        </div>
      </div>
    </div>
  );
}
