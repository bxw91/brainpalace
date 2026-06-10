import { useEffect } from "react";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import {
  SigmaContainer,
  useLoadGraph,
  useRegisterEvents,
} from "@react-sigma/core";
import "@react-sigma/core/lib/react-sigma.min.css";
import type { GraphSubgraph } from "../api/types";

/** Stable color per entity label. */
const LABEL_COLORS = [
  "#2dd4bf",
  "#38bdf8",
  "#f59e0b",
  "#e879f9",
  "#34d399",
  "#f87171",
  "#a78bfa",
];
const colorFor = (label: string | null) => {
  const s = label ?? "";
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return LABEL_COLORS[h % LABEL_COLORS.length];
};

function LoadAndListen({
  data,
  onNodeClick,
}: {
  data: GraphSubgraph;
  onNodeClick: (id: string) => void;
}) {
  const loadGraph = useLoadGraph();
  const registerEvents = useRegisterEvents();

  useEffect(() => {
    const g = new Graph({ multi: true });
    const degree = new Map<string, number>();
    data.edges.forEach((e) => {
      degree.set(e.source, (degree.get(e.source) ?? 0) + 1);
      degree.set(e.target, (degree.get(e.target) ?? 0) + 1);
    });
    data.nodes.forEach((n, i) => {
      g.addNode(n.id, {
        label: n.name,
        color: colorFor(n.label),
        size: 4 + Math.min(10, Math.log2(1 + (degree.get(n.id) ?? 0)) * 3),
        // ForceAtlas2 needs initial coordinates; a unit circle works.
        x: Math.cos((2 * Math.PI * i) / Math.max(1, data.nodes.length)),
        y: Math.sin((2 * Math.PI * i) / Math.max(1, data.nodes.length)),
      });
    });
    data.edges.forEach((e) => {
      if (g.hasNode(e.source) && g.hasNode(e.target)) {
        try {
          g.addEdgeWithKey(e.id, e.source, e.target, {
            label: e.label ?? "",
            color: "#1e2c3a",
            size: 1,
          });
        } catch {
          // Duplicate edge key — skip silently (can occur when expand merges
          // produce repeated edge ids across multiple expansions).
        }
      }
    });
    forceAtlas2.assign(g, {
      iterations: 120,
      settings: forceAtlas2.inferSettings(g),
    });
    loadGraph(g);
  }, [data, loadGraph]);

  useEffect(() => {
    registerEvents({
      clickNode: ({ node }) => onNodeClick(node),
    });
  }, [registerEvents, onNodeClick]);

  return null;
}

/**
 * WebGL graph canvas (sigma). Loaded via React.lazy from the Graph tab so the
 * viz stack never lands in the main bundle. Click a node to expand it.
 */
export default function GraphCanvas({
  data,
  onNodeClick,
}: {
  data: GraphSubgraph;
  onNodeClick: (id: string) => void;
}) {
  return (
    <div data-testid="graph-canvas" className="h-[480px] overflow-hidden rounded-xl border border-line">
      <SigmaContainer
        style={{ height: "100%", background: "#0b1118" }}
        settings={{
          labelColor: { color: "#e6edf3" },
          labelSize: 11,
          renderEdgeLabels: false,
        }}
      >
        <LoadAndListen data={data} onNodeClick={onNodeClick} />
      </SigmaContainer>
    </div>
  );
}
