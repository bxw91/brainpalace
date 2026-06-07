import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Boxes, Share2, HardDrive, GitCommit, RotateCcw, Power } from "lucide-react";
import { getInstanceStatus, gitReindex } from "../api/client";
import { StatCard } from "../components/StatCard";
import { ConfirmDialog } from "../components/ConfirmDialog";
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

type GraphInfo = {
  enabled?: boolean;
  initialized?: boolean;
  entity_count?: number;
  relationship_count?: number;
  store_type?: string;
};

export function Graph({ instanceId }: { instanceId?: string }) {
  const ctx = useOptionalSelectedInstance();
  const id = instanceId ?? ctx?.selectedId ?? null;
  const { toast } = useToast();
  const qc = useQueryClient();
  const [reindexOpen, setReindexOpen] = useState(false);

  const statusQ = useQuery({
    queryKey: ["status", id],
    queryFn: () => getInstanceStatus(id!),
    enabled: !!id,
    retry: false,
  });

  const reindexM = useMutation({
    mutationFn: () => gitReindex(id!),
    onSuccess: () => {
      setReindexOpen(false);
      toast("Git history re-index started.", "success");
      qc.invalidateQueries({ queryKey: ["status", id] });
      qc.invalidateQueries({ queryKey: ["jobs", id] });
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Failed to re-index git history.", "error"),
  });

  if (!id) {
    return <NoInstance testId="tab-graph" message="Select an instance to inspect its knowledge graph." />;
  }
  if (isUnreachable(statusQ.error)) {
    return <StoppedState testId="graph-stopped" />;
  }
  if (statusQ.isError) {
    return (
      <ErrorState
        testId="graph-error"
        message={(statusQ.error as Error)?.message}
        onRetry={() => statusQ.refetch()}
        retrying={statusQ.isFetching}
      />
    );
  }
  if (statusQ.isLoading || !statusQ.data) {
    return (
      <div data-testid="tab-graph">
        <TabSkeleton rows={2} />
      </div>
    );
  }

  const g = (statusQ.data.graph_index ?? {}) as GraphInfo;
  const gitCommits = (statusQ.data.git_commits as number | undefined) ?? 0;
  const enabled = !!g.enabled;

  return (
    <div data-testid="tab-graph" className="flex flex-col gap-6">
      <div className="flex items-baseline justify-between">
        <div>
          <p className="eyebrow">Knowledge graph (GraphRAG)</p>
          <h2 className="mt-0.5 flex items-center gap-2 font-display text-base font-semibold tracking-tight">
            {enabled ? (
              <span className="inline-flex items-center gap-1.5 rounded-md bg-run/15 px-2 py-0.5 text-xs font-medium text-run">
                <Power className="h-3 w-3" aria-hidden="true" /> enabled
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-md bg-ink-600 px-2 py-0.5 text-xs font-medium text-fg-muted">
                <Power className="h-3 w-3" aria-hidden="true" /> disabled
              </span>
            )}
            {g.store_type && (
              <span className="font-mono text-xs uppercase tracking-wider text-fg-faint">
                {g.store_type}
              </span>
            )}
          </h2>
        </div>
        <button
          type="button"
          data-testid="btn-git-reindex"
          onClick={() => setReindexOpen(true)}
          className="btn-danger btn-sm"
        >
          <RotateCcw className="h-4 w-4" aria-hidden="true" /> Re-index git history
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          testId="stat-graph-entities"
          label="Entities"
          value={fmt(g.entity_count ?? 0)}
          tone="accent"
          icon={<Boxes className="h-4 w-4" aria-hidden="true" />}
        />
        <StatCard
          testId="stat-graph-rels"
          label="Relationships"
          value={fmt(g.relationship_count ?? 0)}
          tone="accent"
          icon={<Share2 className="h-4 w-4" aria-hidden="true" />}
        />
        <StatCard
          testId="stat-graph-store"
          label="Store"
          value={g.store_type ?? "—"}
          icon={<HardDrive className="h-4 w-4" aria-hidden="true" />}
        />
        <StatCard
          testId="stat-graph-commits"
          label="Git commits indexed"
          value={fmt(gitCommits)}
          tone={gitCommits > 0 ? "run" : "idle"}
          icon={<GitCommit className="h-4 w-4" aria-hidden="true" />}
        />
      </div>

      <ConfirmDialog
        open={reindexOpen}
        title="Re-index git history?"
        message="This walks the full commit history and rebuilds the temporal graph. It can take a while and runs as a background job."
        confirmLabel="Re-index"
        tone="danger"
        busy={reindexM.isPending}
        onConfirm={() => reindexM.mutate()}
        onCancel={() => setReindexOpen(false)}
      />
    </div>
  );
}
