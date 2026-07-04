import { lazy, Suspense, useState, useEffect, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Boxes, Share2, HardDrive, GitCommit, RotateCcw, Power, Compass, Hammer } from "lucide-react";
import { getInstanceStatus, gitReindex, graphRebuild, searchGraphNodes, getGraphNeighbors, getGraphTopNodes } from "../api/client";
import type { GraphNodeHit } from "../api/types";
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
import { buildExpansion, NEIGHBOR_LIMIT } from "./graphExpansion";
import type { Expansion } from "./graphExpansion";
import { filterSubgraph } from "./graphFilters";
import { NodeDetailPanel } from "../components/NodeDetailPanel";

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
  const [rebuildOpen, setRebuildOpen] = useState(false);

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

  const rebuildM = useMutation({
    mutationFn: () => graphRebuild(id!),
    onSuccess: (r: unknown) => {
      setRebuildOpen(false);
      toast((r as { message?: string })?.message ?? "Graph index rebuilt.", "success");
      qc.invalidateQueries({ queryKey: ["status", id] });
    },
    onError: (e: unknown) =>
      toast(e instanceof Error ? e.message : "Failed to rebuild graph index.", "error"),
  });

  const [searchText, setSearchText] = useState("");
  const [searchQ, setSearchQ] = useState<string | null>(null);
  const [topNodes, setTopNodes] = useState<GraphNodeHit[] | null>(null);
  const [starting, setStarting] = useState(false);
  const [subgraph, setSubgraph] = useState<Expansion | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [rerooting, setRerooting] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [hiddenKinds, setHiddenKinds] = useState<Set<string>>(new Set());
  const [hiddenEdgeTypes, setHiddenEdgeTypes] = useState<Set<string>>(new Set());

  const GRAPH_DOMAINS = ["code", "doc", "session", "git"] as const;
  const [domains, setDomains] = useState<string[]>(["code"]);
  const toggleDomain = (d: string) =>
    setDomains((prev) =>
      prev.includes(d)
        ? prev.length > 1
          ? prev.filter((x) => x !== d)
          : prev // never allow an empty facet — keep at least one domain on
        : [...prev, d],
    );

  const toggleKind = (k: string) =>
    setHiddenKinds((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  const toggleEdgeType = (t: string) =>
    setHiddenEdgeTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });

  const seedsQ = useQuery({
    queryKey: ["graph-seeds", id, searchQ, domains],
    queryFn: () => searchGraphNodes(id!, searchQ!, 20, domains),
    enabled: !!id && !!searchQ,
    retry: false,
  });

  useEffect(() => {
    if (!panelOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setPanelOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [panelOpen]);

  // Re-root the canvas on a node: rebuild a fresh multi-level expansion and
  // REPLACE the subgraph (never merge). Optionally close the search panel.
  const reroot = async (nodeId: string, closePanel = true) => {
    setRerooting(true);
    try {
      const exp = await buildExpansion(
        (n) => getGraphNeighbors(id!, n, NEIGHBOR_LIMIT, domains),
        nodeId,
        // Merge same-name sibling nodes (symbol vs `./path` vs members) so a
        // node's callers/parents — which extraction may attach to a sibling —
        // are pulled into the view. Exact match on the normalised name only.
        async (name) => {
          const bare = name.replace(/^[./]+/, "");
          if (!bare) return [];
          const norm = (s: string) => s.replace(/^[./]+/, "").toLowerCase();
          const target = norm(name);
          const res = await searchGraphNodes(id!, bare, 50, domains);
          return (res?.nodes ?? [])
            .filter((n) => norm(n.name) === target)
            .map((n) => n.id);
        },
      );
      if (exp.nodes.length <= 1 && exp.edges.length === 0) {
        toast("No connections found for this entity.", "error");
        return;
      }
      setSubgraph(exp);
      setSelected(null);
      setHiddenKinds(new Set());
      setHiddenEdgeTypes(new Set());
      if (closePanel) setPanelOpen(false);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Expand failed.", "error");
    } finally {
      setRerooting(false);
    }
  };

  // Open with no search: pull top hubs into the panel and auto-root the #1 hub
  // so the canvas lands populated; the panel stays open for alternative seeds.
  const startBrowser = async () => {
    setStarting(true);
    try {
      const res = await getGraphTopNodes(id!, 15, domains);
      setTopNodes(res.nodes);
      setSearchQ(null);
      if (res.nodes.length > 0) {
        setPanelOpen(true);
        await reroot(res.nodes[0].id, false);
      } else {
        toast("Graph has no connected entities yet — index more first.", "error");
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not start the graph browser.", "error");
    } finally {
      setStarting(false);
    }
  };

  // Memoise so a fresh object identity is minted ONLY when the seed graph or a
  // filter actually changes — NOT on every background re-render (SSE/status
  // polls). A churning `view` reference would re-fire GraphCanvas's load effect
  // every few seconds, restarting physics and yanking the user's zoom/pan.
  // (Declared before the early returns below to keep hook order stable.)
  const view = useMemo(
    () =>
      subgraph ? filterSubgraph(subgraph, hiddenKinds, hiddenEdgeTypes) : null,
    [subgraph, hiddenKinds, hiddenEdgeTypes],
  );

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

  const kindsInView = subgraph
    ? [...new Set(subgraph.nodes.map((n) => n.label ?? "unknown"))].sort()
    : [];
  const edgeTypesInView = subgraph
    ? [...new Set(subgraph.edges.map((e) => e.label ?? "unknown"))].sort()
    : [];

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
        <div className="flex items-center gap-2">
          <button
            type="button"
            data-testid="btn-graph-rebuild"
            onClick={() => setRebuildOpen(true)}
            className="btn-secondary btn-sm"
          >
            <Hammer className="h-4 w-4" aria-hidden="true" /> Rebuild code graph
          </button>
          <button
            type="button"
            data-testid="btn-git-reindex"
            onClick={() => setReindexOpen(true)}
            className="btn-danger btn-sm"
          >
            <RotateCcw className="h-4 w-4" aria-hidden="true" /> Re-index git history
          </button>
        </div>
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

      <ConfirmDialog
        open={rebuildOpen}
        title="Rebuild code graph?"
        message="Rebuilds the code graph (AST + LSP) from already-indexed chunks. No embedding and no token cost; runs synchronously and may take a moment."
        confirmLabel="Rebuild"
        busy={rebuildM.isPending}
        onConfirm={() => rebuildM.mutate()}
        onCancel={() => setRebuildOpen(false)}
      />

      <div className="panel flex flex-col gap-3 p-5">
        <div className="flex items-center justify-between gap-3">
          <p className="eyebrow">Browse the graph</p>
          <button
            type="button"
            data-testid="btn-graph-start"
            disabled={!enabled || starting}
            onClick={startBrowser}
            className="btn-primary btn-sm"
            title="Open the graph at its most-connected entity — no search needed"
          >
            <Compass className="h-4 w-4" aria-hidden="true" />
            {starting ? "Starting…" : "Start graph browser"}
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-3" data-testid="graph-domain-filter">
          <span className="text-xs font-medium text-fg-muted">Domains</span>
          {GRAPH_DOMAINS.map((d) => (
            <label key={d} className="flex cursor-pointer items-center gap-1.5 text-xs text-fg">
              <input
                type="checkbox"
                data-testid={`chk-domain-${d}`}
                checked={domains.includes(d)}
                onChange={() => toggleDomain(d)}
                className="h-3.5 w-3.5 accent-[var(--accent,#7c6cf2)]"
              />
              <span className="font-mono">{d}</span>
            </label>
          ))}
        </div>
        {subgraph && kindsInView.length > 0 && (
          <div className="flex flex-wrap items-center gap-3" data-testid="graph-kind-filter">
            <span className="text-xs font-medium text-fg-muted">Kinds</span>
            {kindsInView.map((k) => (
              <label key={k} className="flex cursor-pointer items-center gap-1.5 text-xs text-fg">
                <input
                  type="checkbox"
                  data-testid={`chk-kind-${k}`}
                  checked={!hiddenKinds.has(k)}
                  onChange={() => toggleKind(k)}
                  className="h-3.5 w-3.5 accent-[var(--accent,#7c6cf2)]"
                />
                <span className="font-mono">{k}</span>
              </label>
            ))}
          </div>
        )}
        {subgraph && edgeTypesInView.length > 0 && (
          <div className="flex flex-wrap items-center gap-3" data-testid="graph-edgetype-filter">
            <span className="text-xs font-medium text-fg-muted">Edge types</span>
            {edgeTypesInView.map((t) => (
              <label key={t} className="flex cursor-pointer items-center gap-1.5 text-xs text-fg">
                <input
                  type="checkbox"
                  data-testid={`chk-edgetype-${t}`}
                  checked={!hiddenEdgeTypes.has(t)}
                  onChange={() => toggleEdgeType(t)}
                  className="h-3.5 w-3.5 accent-[var(--accent,#7c6cf2)]"
                />
                <span className="font-mono">{t}</span>
              </label>
            ))}
          </div>
        )}
        <p className="text-xs text-fg-faint">
          Jump in at the most-connected entity, or search for a specific seed below.
        </p>
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
                  setPanelOpen(true);
                }
              }}
              className="w-full rounded-lg border border-line bg-ink-900/50 px-3 py-2 text-sm text-fg outline-none placeholder:text-fg-faint focus:border-accent/50 focus:ring-2 focus:ring-accent/30"
            />
          </div>
          <button
            type="button"
            data-testid="btn-graph-search"
            disabled={!searchText.trim()}
            onClick={() => {
              setSearchQ(searchText.trim());
              setPanelOpen(true);
            }}
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

        {/* Slide-in search/seed panel */}
        {panelOpen && (
          <div className="fixed inset-0 z-40">
            <div
              data-testid="graph-panel-backdrop"
              className="absolute inset-0 bg-black/50"
              onClick={() => setPanelOpen(false)}
            />
            <aside
              data-testid="graph-search-panel"
              className="absolute right-0 top-0 flex h-full w-full max-w-sm flex-col gap-3 border-l border-line bg-ink-900 p-5 shadow-2xl"
            >
              <div className="flex items-center justify-between">
                <p className="eyebrow">
                  {seedsQ.data ? "Search results" : "Most-connected entities"}
                </p>
                <button
                  type="button"
                  data-testid="btn-graph-panel-close"
                  onClick={() => setPanelOpen(false)}
                  className="btn-ghost btn-sm"
                  aria-label="Close panel"
                >
                  ✕
                </button>
              </div>
              <p className="text-xs text-fg-faint">
                Pick an entity to center the graph on it.
              </p>
              {rerooting && (
                <p
                  data-testid="graph-panel-loading"
                  className="flex items-center gap-2 text-xs text-fg-muted"
                >
                  <span
                    className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent/30 border-t-accent"
                    aria-hidden="true"
                  />
                  Loading nodes…
                </p>
              )}
              <ul className="flex min-h-0 flex-1 flex-col gap-1.5 overflow-y-auto">
                {(seedsQ.data?.nodes ?? topNodes ?? []).length === 0 && (
                  <li className="text-sm text-fg-faint">No matching entities.</li>
                )}
                {(seedsQ.data?.nodes ?? topNodes ?? []).map((n) => (
                  <li key={n.id}>
                    <button
                      type="button"
                      data-testid={`btn-explore-${n.id}`}
                      onClick={() => reroot(n.id)}
                      className="flex w-full items-center gap-3 rounded-lg border border-line/60 bg-ink-700/30 px-3 py-2 text-left text-sm hover:border-accent/50"
                    >
                      <span className="truncate font-mono text-xs text-fg" title={n.name}>
                        {n.name}
                      </span>
                      <span className="rounded bg-ink-600 px-1.5 py-0.5 font-mono text-[0.65rem] text-fg-muted">
                        {n.label ?? "?"}
                      </span>
                      <span className="ml-auto font-mono text-[0.65rem] text-fg-faint">
                        {n.degree} edge{n.degree === 1 ? "" : "s"}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </aside>
          </div>
        )}

        {subgraph && view && (
          <>
            <p className="text-xs text-fg-faint">
              {view.nodes.length} nodes · {view.edges.length} edges —
              click a node to re-center, or search to pick a new seed.
            </p>
            <div className="relative">
              {rerooting && (
                <div
                  data-testid="graph-reroot-loading"
                  className="absolute inset-0 z-10 flex items-center justify-center gap-2 rounded-lg bg-ink-900/60 backdrop-blur-sm"
                >
                  <span
                    className="h-4 w-4 animate-spin rounded-full border-2 border-accent/30 border-t-accent"
                    aria-hidden="true"
                  />
                  <span className="text-sm text-fg-muted">Loading nodes…</span>
                </div>
              )}
              <Suspense
                fallback={<p className="py-8 text-center text-sm text-fg-faint">Loading canvas…</p>}
              >
                <GraphCanvas
                  data={view}
                  rootId={view.rootId}
                  onNodeClick={(nid) => setSelected(nid)}
                />
              </Suspense>
              {selected && view && (() => {
                const nodesById = new Map(view.nodes.map((n) => [n.id, n]));
                const node = nodesById.get(selected);
                if (!node) return null;
                return (
                  <NodeDetailPanel
                    instanceId={id!}
                    node={node}
                    edges={view.edges}
                    nodesById={nodesById}
                    onReroot={(nid) => reroot(nid)}
                    onSelect={(nid) => setSelected(nid)}
                    onClose={() => setSelected(null)}
                  />
                );
              })()}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
