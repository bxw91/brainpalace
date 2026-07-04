import { useQuery } from "@tanstack/react-query";
import { Crosshair, X } from "lucide-react";
import { getGraphCochange, getGraphImpact, getGraphNodeSource } from "../api/client";
import type { GraphSubgraph } from "../api/types";
import { colorForKind, nodeFile } from "./graphLayout";

type GNode = GraphSubgraph["nodes"][number];
type GEdge = GraphSubgraph["edges"][number];

/**
 * Right-side detail panel for a selected graph node: kind/domain, source
 * location (path:line, 1-based for humans), callers/callees derived from the
 * CURRENT subgraph edges (no extra fetch), a lazy source snippet, and the
 * re-root action that used to live on bare node click.
 */
export function NodeDetailPanel({
  instanceId,
  node,
  edges,
  nodesById,
  onReroot,
  onSelect,
  onClose,
}: {
  instanceId: string;
  node: GNode;
  edges: GEdge[];
  nodesById: Map<string, GNode>;
  onReroot: (id: string) => void;
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const incoming = edges.filter((e) => e.target === node.id && e.source !== node.id);
  const outgoing = edges.filter((e) => e.source === node.id && e.target !== node.id);
  const file = nodeFile(node);
  const line = typeof node.properties?.line === "number" ? node.properties.line : null;

  const snippetQ = useQuery({
    queryKey: ["graph-node-source", instanceId, node.id],
    queryFn: () => getGraphNodeSource(instanceId, node.id),
    retry: false,
  });
  const impactQ = useQuery({
    queryKey: ["graph-node-impact", instanceId, node.id],
    queryFn: () => getGraphImpact(instanceId, node.id),
    retry: false,
  });
  const cochangeQ = useQuery({
    queryKey: ["graph-node-cochange", instanceId, node.id],
    queryFn: () => getGraphCochange(instanceId, node.id),
    retry: false,
  });

  const linkList = (items: GEdge[], dir: "in" | "out", testId: string) => (
    <ul data-testid={testId} className="flex flex-col gap-1">
      {items.length === 0 && <li className="text-xs text-fg-faint">none in view</li>}
      {items.map((e) => {
        const otherId = dir === "in" ? e.source : e.target;
        const other = nodesById.get(otherId);
        return (
          <li key={e.id}>
            <button
              type="button"
              onClick={() => onSelect(otherId)}
              className="flex w-full items-center gap-2 rounded px-1.5 py-0.5 text-left text-xs hover:bg-ink-700/40"
            >
              <span className="font-mono text-fg-faint">{e.label ?? "?"}</span>
              <span className="truncate font-mono text-fg">
                {other?.name ?? otherId}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );

  return (
    <aside
      data-testid="graph-node-panel"
      className="absolute right-0 top-0 z-20 flex h-full w-full max-w-sm flex-col gap-3 overflow-y-auto border-l border-line bg-ink-900 p-4 shadow-2xl"
    >
      <div className="flex items-center justify-between gap-2">
        <span
          className="rounded px-1.5 py-0.5 font-mono text-[0.65rem]"
          style={{ background: colorForKind(node.label) + "33", color: colorForKind(node.label) }}
        >
          {node.label ?? "?"}
        </span>
        <button
          type="button"
          data-testid="btn-node-panel-close"
          onClick={onClose}
          className="btn-ghost btn-sm"
          aria-label="Close node panel"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <p className="break-all font-mono text-sm font-medium text-fg" title={node.id}>
        {node.name}
      </p>
      {file && (
        <p data-testid="node-panel-file" className="break-all font-mono text-xs text-fg-muted">
          {file}
          {line !== null ? `:${line + 1}` : ""}
        </p>
      )}
      <div className="flex items-center gap-2 text-xs text-fg-faint">
        <span>{node.degree ?? 0} edges</span>
        {node.domain && <span className="font-mono">· {node.domain}</span>}
      </div>
      <button
        type="button"
        data-testid="btn-node-reroot"
        onClick={() => onReroot(node.id)}
        className="btn-primary btn-sm"
      >
        <Crosshair className="h-4 w-4" aria-hidden="true" /> Re-root here
      </button>
      <div>
        <p className="eyebrow mb-1">Incoming</p>
        {linkList(incoming, "in", "node-panel-in")}
      </div>
      <div>
        <p className="eyebrow mb-1">Outgoing</p>
        {linkList(outgoing, "out", "node-panel-out")}
      </div>
      <div>
        <p className="eyebrow mb-1">Impact — depends on this</p>
        <ul data-testid="node-panel-impact" className="flex flex-col gap-1">
          {impactQ.isError && (
            <li className="text-xs text-fg-faint">unavailable</li>
          )}
          {impactQ.data && impactQ.data.nodes.length === 0 && (
            <li className="text-xs text-fg-faint">no dependents found</li>
          )}
          {impactQ.data?.nodes.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                onClick={() => onSelect(n.id)}
                className="flex w-full items-center gap-2 rounded px-1.5 py-0.5 text-left text-xs hover:bg-ink-700/40"
              >
                <span className="font-mono text-fg-faint">
                  d{n.depth} {n.via_predicate}
                </span>
                <span className="truncate font-mono text-fg">{n.name}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <p className="eyebrow mb-1">Co-change (git)</p>
        <ul data-testid="node-panel-cochange" className="flex flex-col gap-1">
          {cochangeQ.isError && (
            <li className="text-xs text-fg-faint">unavailable</li>
          )}
          {cochangeQ.data && cochangeQ.data.files.length === 0 && (
            <li className="text-xs text-fg-faint">no co-change history</li>
          )}
          {cochangeQ.data?.files.map((f) => (
            <li
              key={f.file_id}
              className="flex items-center gap-2 px-1.5 py-0.5 text-xs"
            >
              <span className="font-mono text-fg-faint">×{f.shared_commits}</span>
              <span className="truncate font-mono text-fg">{f.name}</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <p className="eyebrow mb-1">Source</p>
        {snippetQ.isLoading && <p className="text-xs text-fg-faint">Loading…</p>}
        {snippetQ.isError && (
          <p className="text-xs text-fg-faint">No source available.</p>
        )}
        {snippetQ.data && (
          <pre
            data-testid="node-panel-snippet"
            className="max-h-64 overflow-auto rounded-md border border-line bg-ink-900/70 p-2 font-mono text-[0.7rem] leading-relaxed text-fg"
          >
            {snippetQ.data.lines
              .map(
                (l, i) =>
                  `${String(snippetQ.data.start_line + i + 1).padStart(4)}  ${l}`,
              )
              .join("\n")}
          </pre>
        )}
      </div>
    </aside>
  );
}
