import type { GraphSubgraph } from "../api/types";

export const RING_RADIUS = 120;

export type Placed = { id: string; x: number; y: number; ring: number };

/**
 * BFS ring distance from `rootId`, then lay each ring out on its own circle.
 * Root sits at the centre; nodes unreachable from root fall to `maxRing + 1`.
 * BFS insertion order keeps siblings adjacent on a ring, which limits crossings
 * without an explicit angular sort.
 */
export function computeConcentricLayout(
  data: GraphSubgraph,
  rootId: string,
): Map<string, Placed> {
  const adj = new Map<string, Set<string>>();
  const ensure = (id: string) => {
    let s = adj.get(id);
    if (!s) {
      s = new Set();
      adj.set(id, s);
    }
    return s;
  };
  data.nodes.forEach((nd) => ensure(nd.id));
  data.edges.forEach((ed) => {
    if (adj.has(ed.source) && adj.has(ed.target)) {
      ensure(ed.source).add(ed.target);
      ensure(ed.target).add(ed.source);
    }
  });

  const ring = new Map<string, number>();
  if (adj.has(rootId)) {
    ring.set(rootId, 0);
    let frontier = [rootId];
    let level = 0;
    while (frontier.length) {
      level += 1;
      const next: string[] = [];
      for (const id of frontier) {
        for (const nb of adj.get(id) ?? []) {
          if (!ring.has(nb)) {
            ring.set(nb, level);
            next.push(nb);
          }
        }
      }
      frontier = next;
    }
  }
  const maxRing = ring.size ? Math.max(...ring.values()) : 0;
  data.nodes.forEach((nd) => {
    if (!ring.has(nd.id)) ring.set(nd.id, maxRing + 1);
  });

  const byRing = new Map<number, string[]>();
  data.nodes.forEach((nd) => {
    const r = ring.get(nd.id)!;
    const arr = byRing.get(r) ?? [];
    arr.push(nd.id);
    byRing.set(r, arr);
  });

  const placed = new Map<string, Placed>();
  for (const [r, ids] of byRing) {
    if (r === 0) {
      placed.set(ids[0], { id: ids[0], x: 0, y: 0, ring: 0 });
      ids.slice(1).forEach((id, i) => {
        const a = (2 * Math.PI * i) / Math.max(1, ids.length - 1);
        placed.set(id, { id, x: Math.cos(a), y: Math.sin(a), ring: 0 });
      });
      continue;
    }
    const radius = r * RING_RADIUS;
    ids.forEach((id, i) => {
      const a = (2 * Math.PI * i) / ids.length;
      placed.set(id, { id, x: Math.cos(a) * radius, y: Math.sin(a) * radius, ring: r });
    });
  }
  return placed;
}

/** Explicit kind→color map (legend + node fill). Code kinds are all distinct;
 * doc/session/infra/git kinds share a family hue per domain. Extend here when
 * a new EntityType lands (Spec C adds Commit/Author). */
export const KIND_COLORS: Record<string, string> = {
  // code — one distinct color per kind
  File: "#38bdf8",
  Folder: "#64748b",
  Class: "#f59e0b",
  Method: "#fbbf24",
  Function: "#34d399",
  Interface: "#2dd4bf",
  Enum: "#a3e635",
  Module: "#94a3b8",
  Package: "#818cf8",
  Decorator: "#e879f9",
  Endpoint: "#fb7185",
  // doc family
  DesignDoc: "#c084fc",
  UserDoc: "#a855f7",
  PRD: "#9333ea",
  Runbook: "#c084fc",
  README: "#a855f7",
  APIDoc: "#9333ea",
  // session family
  Decision: "#f472b6",
  Error: "#f87171",
  Session: "#f9a8d4",
  Tool: "#fda4af",
  Task: "#fbcfe8",
  // infra family
  Service: "#4ade80",
  Database: "#22c55e",
  ConfigFile: "#86efac",
  // git family (Spec C)
  Commit: "#fb923c",
  Author: "#fdba74",
};
export const FALLBACK_KIND_COLOR = "#7c8b9d";
export const colorForKind = (label: string | null): string =>
  KIND_COLORS[label ?? ""] ?? FALLBACK_KIND_COLOR;

/** Source file for a node: explicit properties.path first, else derived from a
 * canonical symbol id ("abs/path.py:fqname" — fqname never contains "/"), else
 * the id itself when it IS a path (File/Folder nodes). */
export function nodeFile(n: {
  id: string;
  properties?: Record<string, unknown> | null;
}): string | null {
  const p = n.properties?.path;
  if (typeof p === "string" && p) return p;
  const id = n.id;
  if (id.includes("/")) {
    const colon = id.lastIndexOf(":");
    return colon > id.lastIndexOf("/") ? id.slice(0, colon) : id;
  }
  return null;
}

export function formatNodeTooltip(
  n: {
    name: string;
    label: string | null;
    id?: string;
    properties?: Record<string, unknown> | null;
  },
  ring: number,
  degree: number,
): { name: string; meta: string } {
  const type = n.label ?? "unknown";
  const file = n.id ? nodeFile({ id: n.id, properties: n.properties }) : null;
  const base = file ? ` · ${file.split("/").pop()}` : "";
  return { name: n.name, meta: `${type}${base} · degree ${degree} · level ${ring}` };
}
