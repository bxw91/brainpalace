import type { Expansion } from "./graphExpansion";

/** Client-side view filter over the expanded subgraph (≤300 nodes — cheap).
 * Hidden kinds remove nodes (and any edge touching them); hidden edge types
 * remove edges only. The root always survives so the canvas keeps its anchor. */
export function filterSubgraph(
  data: Expansion,
  hiddenKinds: Set<string>,
  hiddenEdgeTypes: Set<string>,
): Expansion {
  const nodes = data.nodes.filter(
    (n) => n.id === data.rootId || !hiddenKinds.has(n.label ?? "unknown"),
  );
  const keep = new Set(nodes.map((n) => n.id));
  const edges = data.edges.filter(
    (e) =>
      keep.has(e.source) &&
      keep.has(e.target) &&
      !hiddenEdgeTypes.has(e.label ?? "unknown"),
  );
  return { rootId: data.rootId, nodes, edges };
}
