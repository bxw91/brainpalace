import { lazy, Suspense, useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Boxes, Share2, HardDrive, GitCommit, RotateCcw, Power } from "lucide-react";
import { getInstanceStatus, gitReindex, searchGraphNodes, getGraphNeighbors } from "../api/client";
import type { GraphSubgraph } from "../api/types";
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

const GraphCanvas = lazy(() => import("../components/GraphCanvas"));

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

  const [searchText, setSearchText] = useState("");
  const [searchQ, setSearchQ] = useState<string | null>(null);
  const [subgraph, setSubgraph] = useState<GraphSubgraph | null>(null);
  const subgraphRef = useRef(subgraph);
  useEffect(() => {
    subgraphRef.current = subgraph;
  }, [subgraph]);

  const NODE_CAP = 500;

  const seedsQ = useQuery({
    queryKey: ["graph-seeds", id, searchQ],
    queryFn: () => searchGraphNodes(id!, searchQ!),
    enabled: !!id && !!searchQ,
    retry: false,
  });

  const expand = async (nodeId: string) => {
    try {
      const next = await getGraphNeighbors(id!, nodeId, 200);
      const prev = subgraphRef.current;
      const nodes = new Map(
        (prev?.nodes ?? []).map((n) => [n.id, n] as const),
      );
      next.nodes.forEach((n) => nodes.set(n.id, n));
      if (nodes.size > NODE_CAP) {
        toast(`Node cap (${NODE_CAP}) reached — narrow your seed.`, "error");
        return;
      }
      const edges = new Map(
        (prev?.edges ?? []).map((e) => [e.id, e] as const),
      );
      next.edges.forEach((e) => edges.set(e.id, e));
      setSubgraph({ nodes: [...nodes.values()], edges: [...edges.values()] });
    } catch (e) {
      toast(e instanceof Error ? e.message : "Expand failed.", "error");
    }
  };

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

      <div className="panel flex flex-col gap-3 p-5">
        <p className="eyebrow">Browse the graph</p>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-0 flex-1">
            <label
              htmlFor="input-graph-search"
              className="mb-1.5 block text-xs font-medium text-fg-muted"
            >
              Find a seed entity
            </label>
            <input
              id="input-graph-search"
              data-testid="input-graph-search"
              type="text"
              value={searchText}
              placeholder="Class, function, file, decision…"
              onChange={(e) => setSearchText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && searchText.trim()) {
                  setSearchQ(searchText.trim());
                }
              }}
              className="w-full rounded-lg border border-line bg-ink-900/50 px-3 py-2 text-sm text-fg outline-none placeholder:text-fg-faint focus:border-accent/50 focus:ring-2 focus:ring-accent/30"
            />
          </div>
          <button
            type="button"
            data-testid="btn-graph-search"
            disabled={!searchText.trim()}
            onClick={() => setSearchQ(searchText.trim())}
            className="btn-primary btn-sm"
          >
            Search
          </button>
        </div>

        {seedsQ.isError && (
          <p
            data-testid="graph-search-error"
            className="text-sm text-red-400"
          >
            {(seedsQ.error as Error)?.message ?? "Search failed."}
          </p>
        )}

        {seedsQ.isFetching && (
          <p className="text-sm text-fg-faint">Searching…</p>
        )}

        {seedsQ.data && (
          <ul className="flex flex-col gap-1.5">
            {seedsQ.data.nodes.length === 0 && (
              <p className="text-sm text-fg-faint">No matching entities.</p>
            )}
            {seedsQ.data.nodes.map((n) => (
              <li
                key={n.id}
                className="flex items-center gap-3 rounded-lg border border-line/60 bg-ink-700/30 px-3 py-2 text-sm"
              >
                <span className="truncate font-mono text-xs text-fg" title={n.name}>
                  {n.name}
                </span>
                <span className="rounded bg-ink-600 px-1.5 py-0.5 font-mono text-[0.65rem] text-fg-muted">
                  {n.label ?? "?"}
                </span>
                <span className="font-mono text-[0.65rem] text-fg-faint">
                  {n.degree} edge{n.degree === 1 ? "" : "s"}
                </span>
                <button
                  type="button"
                  data-testid={`btn-explore-${n.id}`}
                  onClick={() => expand(n.id)}
                  className="btn-ghost btn-sm ml-auto"
                >
                  Explore
                </button>
              </li>
            ))}
          </ul>
        )}

        {subgraph && (
          <>
            <p className="text-xs text-fg-faint">
              {subgraph.nodes.length} nodes · {subgraph.edges.length} edges —
              click a node to expand, search again to add seeds.
            </p>
            <Suspense
              fallback={<p className="py-8 text-center text-sm text-fg-faint">Loading canvas…</p>}
            >
              <GraphCanvas data={subgraph} onNodeClick={expand} />
            </Suspense>
          </>
        )}
      </div>
    </div>
  );
}
