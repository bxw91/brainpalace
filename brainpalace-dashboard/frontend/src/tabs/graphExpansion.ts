import type { GraphSubgraph } from "../api/types";

export const DEPTH = 4;
export const FAN_OUT = 8;
export const MAX_NODES = 300;
export const NEIGHBOR_LIMIT = 200;

type FetchNeighbors = (nodeId: string) => Promise<GraphSubgraph>;
export type Expansion = GraphSubgraph & { rootId: string };

/**
 * Breadth-first expansion from `rootId`: up to DEPTH rings. Level 1 keeps EVERY
 * direct neighbour (the selected node's full neighbourhood); deeper rings keep
 * FAN_OUT children per frontier node. Capped at MAX_NODES total. One fetch per
 * frontier node, run in parallel per level. Callers REPLACE their subgraph with
 * the result — no merge.
 */
/**
 * Resolve sibling node ids that represent the SAME concept as `name` but were
 * split into separate, unlinked graph nodes by extraction (e.g. the symbol
 * `graphExpansion`, the path `./graphExpansion`). Returning their ids lets the
 * expansion treat them as co-roots so callers attached to a sibling show up.
 */
type ResolveSiblings = (name: string) => Promise<string[]>;

export async function buildExpansion(
  fetchNeighbors: FetchNeighbors,
  rootId: string,
  resolveSiblings?: ResolveSiblings,
): Promise<Expansion> {
  const nodes = new Map<string, GraphSubgraph["nodes"][number]>();
  const edges = new Map<string, GraphSubgraph["edges"][number]>();
  const visited = new Map<string, number>([[rootId, 0]]);
  // Accumulated within-subgraph edge count — fallback hub score when the
  // server doesn't echo each node's true active-edge `degree`.
  const degree = new Map<string, number>();
  const bump = (id: string) => degree.set(id, (degree.get(id) ?? 0) + 1);
  // True global degree from the neighbors payload. Ranking fan-out by this
  // (not the accumulated count) lets BFS pick real hubs and reach deep levels;
  // at level 1 every candidate has accumulated degree 1, so the old score
  // ranked alphabetically and picked leaves, stalling expansion at ~6 nodes.
  const trueDegree = (id: string) => nodes.get(id)?.degree ?? degree.get(id) ?? 0;

  let frontier: string[] = [rootId];

  // Seed same-name siblings as additional roots (level 0). Graph extraction
  // often splits one file into unlinked nodes, so a "calls/imports" edge lands
  // on a sibling rather than the searched node; without this the browser shows
  // only the node's own members and never its callers.
  if (resolveSiblings) {
    // Best-effort: a sibling-lookup failure must never abort the main
    // expansion, so the graph still renders if the search call errors.
    try {
      const rootResp = await fetchNeighbors(rootId);
      const rootName = rootResp.nodes.find((n) => n.id === rootId)?.name;
      if (rootName) {
        const sibs = await resolveSiblings(rootName);
        for (const s of sibs) {
          if (!visited.has(s)) {
            visited.set(s, 0);
            frontier.push(s);
          }
        }
      }
    } catch {
      // ignore — proceed with the searched node alone
    }
  }

  for (let level = 1; level <= DEPTH; level++) {
    if (frontier.length === 0 || nodes.size >= MAX_NODES) break;
    const results = await Promise.all(frontier.map((n) => fetchNeighbors(n)));

    // Absorb every returned node (for name/label) + edges (for degree).
    results.forEach((resp) => {
      resp.nodes.forEach((n) => {
        if (!nodes.has(n.id)) nodes.set(n.id, n);
      });
      resp.edges.forEach((e) => {
        if (!edges.has(e.id)) {
          edges.set(e.id, e);
          bump(e.source);
          bump(e.target);
        }
      });
    });

    // Level 1 shows EVERY direct neighbour of the selected node (its full
    // neighbourhood — what the user asked for); deeper rings keep the FAN_OUT
    // cap so a hub doesn't explode the canvas. MAX_NODES still bounds the total.
    const cap = level === 1 ? Infinity : FAN_OUT;
    const nextFrontier: string[] = [];
    frontier.forEach((srcId, i) => {
      const cands = new Set<string>();
      results[i].edges.forEach((e) => {
        const other =
          e.source === srcId ? e.target : e.target === srcId ? e.source : null;
        if (other && other !== srcId && !visited.has(other)) cands.add(other);
      });
      const ranked = [...cands].sort(
        (a, b) => trueDegree(b) - trueDegree(a) || (a < b ? -1 : 1),
      );
      for (const c of ranked.slice(0, cap)) {
        if (nodes.size >= MAX_NODES) break;
        if (visited.has(c)) continue;
        visited.set(c, level);
        nextFrontier.push(c);
      }
    });
    frontier = nextFrontier;
  }

  // Root may not be echoed by its own neighbors response.
  if (!nodes.has(rootId)) nodes.set(rootId, { id: rootId, name: rootId, label: null });

  // Keep only selected (visited) nodes; drop absorbed-but-unselected ones so
  // fan-out / cap actually bound the result. Edges need both endpoints kept.
  const kept = [...nodes.values()].filter((n) => visited.has(n.id));
  const keptIds = new Set(kept.map((n) => n.id));
  const keptEdges = [...edges.values()].filter(
    (e) => keptIds.has(e.source) && keptIds.has(e.target),
  );
  return { nodes: kept, edges: keptEdges, rootId };
}
