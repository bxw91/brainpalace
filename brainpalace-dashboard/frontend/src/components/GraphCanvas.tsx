import { useEffect, useRef, useState } from "react";
import Graph, { MultiGraph } from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import FA2Layout from "graphology-layout-forceatlas2/worker";
import {
  SigmaContainer,
  useLoadGraph,
  useRegisterEvents,
  useSigma,
} from "@react-sigma/core";
import "@react-sigma/core/lib/react-sigma.min.css";
import { drawDiscNodeLabel, EdgeArrowProgram } from "sigma/rendering";
import { EdgeCurvedArrowProgram, indexParallelEdgesIndex } from "@sigma/edge-curve";
import type { Settings } from "sigma/settings";
import type { NodeDisplayData, PartialButFor } from "sigma/types";
import type { GraphSubgraph } from "../api/types";
import { computeConcentricLayout, formatNodeTooltip, colorForKind } from "./graphLayout";

/**
 * Hover label renderer with a DARK rounded box — sigma's default fills the box
 * white and then draws the label in `labelColor` (also white here), so the
 * hovered name was white-on-white and invisible. Same geometry as the built-in,
 * recoloured for the dark canvas.
 */
function drawDarkNodeHover(
  context: CanvasRenderingContext2D,
  data: PartialButFor<NodeDisplayData, "x" | "y" | "size" | "label" | "color">,
  settings: Settings,
) {
  const size = settings.labelSize;
  context.font = `${settings.labelWeight} ${size}px ${settings.labelFont}`;
  context.fillStyle = "#0b1118";
  context.shadowOffsetX = 0;
  context.shadowOffsetY = 0;
  context.shadowBlur = 8;
  context.shadowColor = "#000";
  const PADDING = 2;
  if (typeof data.label === "string") {
    const textWidth = context.measureText(data.label).width;
    const boxWidth = Math.round(textWidth + 5);
    const boxHeight = Math.round(size + 2 * PADDING);
    const radius = Math.max(data.size, size / 2) + PADDING;
    const angleRadian = Math.asin(boxHeight / 2 / radius);
    const xDeltaCoord = Math.sqrt(
      Math.abs(radius ** 2 - (boxHeight / 2) ** 2),
    );
    context.beginPath();
    context.moveTo(data.x + xDeltaCoord, data.y + boxHeight / 2);
    context.lineTo(data.x + radius + boxWidth, data.y + boxHeight / 2);
    context.lineTo(data.x + radius + boxWidth, data.y - boxHeight / 2);
    context.lineTo(data.x + xDeltaCoord, data.y - boxHeight / 2);
    context.arc(data.x, data.y, radius, angleRadian, -angleRadian);
    context.closePath();
    context.fill();
  } else {
    context.beginPath();
    context.arc(data.x, data.y, data.size + PADDING, 0, Math.PI * 2);
    context.closePath();
    context.fill();
  }
  context.shadowBlur = 0;
  drawDiscNodeLabel(context, data, settings);
}

type Hover = { name: string; meta: string; x: number; y: number } | null;

const degreeMap = (data: GraphSubgraph) => {
  const d = new Map<string, number>();
  data.edges.forEach((e) => {
    d.set(e.source, (d.get(e.source) ?? 0) + 1);
    d.set(e.target, (d.get(e.target) ?? 0) + 1);
  });
  return d;
};

// Shared ForceAtlas2 tuning for the warm-start pass and the live worker.
// linLog + outbound-attraction separate communities (Obsidian-like clusters);
// adjustSizes stops node overlap; gravity keeps loose nodes on-canvas.
const fa2Settings = (graph: Graph) => ({
  ...forceAtlas2.inferSettings(graph),
  barnesHutOptimize: graph.order > 150,
  adjustSizes: true,
  linLogMode: true,
  outboundAttractionDistribution: true,
  gravity: 0.5,
  scalingRatio: 8,
  slowDown: 2,
});

function LoadAndListen({
  data,
  rootId,
  onNodeClick,
  setHover,
}: {
  data: GraphSubgraph;
  rootId: string;
  onNodeClick: (id: string) => void;
  setHover: (h: Hover) => void;
}) {
  const loadGraph = useLoadGraph();
  const registerEvents = useRegisterEvents();
  const sigma = useSigma();
  const hoveredRef = useRef<string | null>(null);
  const draggedRef = useRef<string | null>(null);
  const movedRef = useRef(false);
  const supervisorRef = useRef<FA2Layout | null>(null);
  // Coordinates from the previous subgraph — surviving nodes re-seed at their
  // old spot so a re-root reads as an incremental shift, not a re-scramble.
  const prevPosRef = useRef<Map<string, { x: number; y: number }>>(new Map());
  // Track the root we last fit the camera to. The camera resets (zoom + pan)
  // ONLY when the user picks a new seed (rootId changes) — a background data
  // refresh that keeps the same root must preserve the user's zoom/pan.
  const fitRootRef = useRef<string | null>(null);

  useEffect(() => {
    const live0 = sigma.getGraph();
    if (live0.order > 0) {
      const snap = new Map<string, { x: number; y: number }>();
      live0.forEachNode((n, a) =>
        snap.set(n, { x: a.x as number, y: a.y as number }),
      );
      prevPosRef.current = snap;
    }

    const g = new Graph({ multi: true });
    // BFS rings only SEED the force layout (spread + distinct start coords so
    // ForceAtlas2 doesn't get coincident points); final x/y come from the
    // force passes below. The `ring` value still feeds the tooltip's "level".
    const placed = computeConcentricLayout(data, rootId);
    const degree = degreeMap(data);
    data.nodes.forEach((n) => {
      const p = placed.get(n.id) ?? { x: 0, y: 0, ring: 0 };
      // Shrink dots by BFS ring so each deeper level is visibly smaller — the
      // root is largest, ring 4 ~45% of base. Makes depth legible when zoomed in.
      const ringShrink = Math.max(0.45, 1 - p.ring * 0.18);
      const prev = prevPosRef.current.get(n.id);
      g.addNode(n.id, {
        label: n.name,
        color: colorForKind(n.label),
        size:
          (4 + Math.min(12, Math.log2(1 + (degree.get(n.id) ?? 0)) * 3)) *
            ringShrink +
          (n.id === rootId ? 4 : 0),
        // Nudge the root off dead-centre so it isn't a fixed coincident seed.
        x: prev ? prev.x : p.x || 0.1,
        y: prev ? prev.y : p.y || 0.1,
      });
    });
    // `contains` and `defined_in` are exact inverses stored as two edges; draw
    // only one per pair so a parent↔child link isn't a doubled line.
    const INVERSE = new Set(["contains", "defined_in"]);
    const seenPair = new Set<string>();
    data.edges.forEach((e) => {
      if (!g.hasNode(e.source) || !g.hasNode(e.target)) return;
      if (INVERSE.has(e.label ?? "")) {
        const key = [e.source, e.target].sort().join("\u0000");
        if (seenPair.has(key)) return;
        seenPair.add(key);
      }
      try {
        g.addEdgeWithKey(e.id, e.source, e.target, {
          label: e.label ?? "",
          color: "#243447",
          size: 1,
        });
      } catch {
        // Duplicate edge key — skip silently.
      }
    });

    // Parallel edges between the same pair overdraw as straight lines; index
    // them and render every non-first parallel as a curve so each arrow stays
    // visible. Non-parallel edges stay on the cheaper straight arrow program.
    indexParallelEdgesIndex(g, {
      edgeIndexAttribute: "parallelIndex",
      edgeMinIndexAttribute: "parallelMinIndex",
      edgeMaxIndexAttribute: "parallelMaxIndex",
    });
    g.forEachEdge((edge, attrs) => {
      const idx = attrs.parallelIndex as number | undefined;
      const max = attrs.parallelMaxIndex as number | undefined;
      if (typeof idx === "number" && typeof max === "number" && max > 0) {
        g.mergeEdgeAttributes(edge, {
          type: idx > 0 ? "curved" : "straight",
          curvature: max > 0 ? (0.35 * idx) / max : 0,
        });
      } else {
        g.setEdgeAttribute(edge, "type", "straight");
      }
    });

    // Warm start: a short synchronous pass so the very first frame is already
    // clustered (not a ring) before the live worker takes over.
    if (g.order > 1) {
      forceAtlas2.assign(g, { iterations: 60, settings: fa2Settings(g) });
    }
    loadGraph(g);
    // Refit the camera ONLY on a genuine re-root (new seed): sigma re-normalises
    // coords as the worker spreads them, so this one fit keeps the whole graph
    // in frame while it animates. A same-root refresh (background re-index) must
    // NOT reset — it would fight the user's current zoom/pan every few seconds.
    if (fitRootRef.current !== rootId) {
      fitRootRef.current = rootId;
      sigma.getCamera().animatedReset();
    }

    // Live physics (Obsidian-style): the worker mutates sigma's OWN graph (the
    // loaded copy, not `g`) so the canvas animates and settles. Stop after a
    // few seconds so it doesn't spin the CPU forever; drag/re-root also stop it.
    supervisorRef.current?.kill();
    supervisorRef.current = null;
    let settleTimer: ReturnType<typeof setTimeout> | undefined;
    const live = sigma.getGraph();
    if (live.order > 1) {
      const supervisor = new FA2Layout(live, { settings: fa2Settings(live) });
      supervisorRef.current = supervisor;
      supervisor.start();
      settleTimer = setTimeout(() => supervisor.stop(), 3000);
    }
    return () => {
      if (settleTimer) clearTimeout(settleTimer);
      supervisorRef.current?.kill();
      supervisorRef.current = null;
    };
  }, [data, rootId, loadGraph, sigma]);

  useEffect(() => {
    const placed = computeConcentricLayout(data, rootId);
    const degree = degreeMap(data);
    const neighborsOf = (id: string) => {
      const s = new Set<string>([id]);
      data.edges.forEach((e) => {
        if (e.source === id) s.add(e.target);
        if (e.target === id) s.add(e.source);
      });
      return s;
    };

    sigma.setSetting("nodeReducer", (node, attrs) => {
      const h = hoveredRef.current;
      if (!h) return attrs;
      // On hover, force the hovered node + its neighbours to show their names
      // (overriding the zoom threshold) and dim everyone else.
      return neighborsOf(h).has(node)
        ? { ...attrs, forceLabel: true }
        : { ...attrs, color: "#1b2733", label: "" };
    });
    sigma.setSetting("edgeReducer", (edge, attrs) => {
      const h = hoveredRef.current;
      if (!h) return attrs;
      const gr = sigma.getGraph();
      return gr.source(edge) === h || gr.target(edge) === h
        ? { ...attrs, color: "#3b82f6", size: 2 }
        : { ...attrs, color: "#141d28" };
    });

    registerEvents({
      // Drag a node (Obsidian-style). Grabbing one stops the live worker so the
      // node holds where you drop it instead of being pulled back each tick.
      downNode: ({ node }) => {
        draggedRef.current = node;
        movedRef.current = false;
        supervisorRef.current?.stop();
        sigma.getGraph().setNodeAttribute(node, "highlighted", true);
      },
      mousemovebody: (e) => {
        const n = draggedRef.current;
        if (!n) return;
        movedRef.current = true;
        const pos = sigma.viewportToGraph(e);
        sigma.getGraph().setNodeAttribute(n, "x", pos.x);
        sigma.getGraph().setNodeAttribute(n, "y", pos.y);
        // Keep the camera still while dragging a node.
        e.preventSigmaDefault();
        e.original.preventDefault();
        e.original.stopPropagation();
      },
      mouseup: () => {
        const n = draggedRef.current;
        if (n) sigma.getGraph().removeNodeAttribute(n, "highlighted");
        draggedRef.current = null;
      },
      // Re-root only on a genuine click — swallow the click that ends a drag.
      clickNode: ({ node }) => {
        if (movedRef.current) {
          movedRef.current = false;
          return;
        }
        onNodeClick(node);
      },
      enterNode: ({ node }) => {
        hoveredRef.current = node;
        const nd = data.nodes.find((x) => x.id === node);
        const p = placed.get(node);
        const t = formatNodeTooltip(
          nd ?? { name: node, label: null, id: node },
          p?.ring ?? 0,
          degree.get(node) ?? 0,
        );
        const attrs = sigma.getGraph().getNodeAttributes(node) as {
          x: number;
          y: number;
        };
        const vp = sigma.graphToViewport(attrs);
        setHover({ name: t.name, meta: t.meta, x: vp.x, y: vp.y });
        sigma.refresh();
      },
      leaveNode: () => {
        hoveredRef.current = null;
        setHover(null);
        sigma.refresh();
      },
    });
  }, [data, rootId, sigma, registerEvents, onNodeClick, setHover]);

  return null;
}

/**
 * WebGL graph canvas (sigma). Lazy-loaded from the Graph tab so the viz stack
 * never lands in the main bundle. Obsidian-style: live ForceAtlas2 physics
 * (warm-start pass + a worker that animates and settles) so connected entities
 * cluster; drag a node to reposition it; labels appear on zoom-in; click a node
 * to re-root (camera refits); hover for a tooltip with neighbor highlight.
 */
export default function GraphCanvas({
  data,
  rootId,
  onNodeClick,
}: {
  data: GraphSubgraph;
  rootId: string;
  onNodeClick: (id: string) => void;
}) {
  const [hover, setHover] = useState<Hover>(null);
  return (
    <div
      data-testid="graph-canvas"
      className="relative h-[480px] overflow-hidden rounded-xl border border-line"
    >
      <SigmaContainer
        // Sigma's internal graph must be multi: the expanded subgraph contains
        // self-loops (e.g. graph_store→graph_store) and parallel edges between
        // the same pair. useLoadGraph imports into THIS graph, so a default
        // simple graph throws "an edge linking X to Y already exists".
        graph={MultiGraph}
        style={{ height: "100%", background: "#0b1118" }}
        settings={{
          labelColor: { color: "#e6edf3" },
          labelSize: 11,
          renderEdgeLabels: true,
          edgeLabelColor: { color: "#5b6b7c" },
          edgeLabelSize: 9,
          defaultEdgeType: "straight",
          edgeProgramClasses: {
            straight: EdgeArrowProgram,
            curved: EdgeCurvedArrowProgram,
          },
          // Obsidian-style: labels appear only for nodes rendered large enough
          // (hubs, or anything once you zoom in), so a zoomed-out graph stays
          // clean instead of a wall of overlapping text.
          labelRenderedSizeThreshold: 12,
          // Dark hover box so the white node name stays readable.
          defaultDrawNodeHover: drawDarkNodeHover,
        }}
      >
        <LoadAndListen
          data={data}
          rootId={rootId}
          onNodeClick={onNodeClick}
          setHover={setHover}
        />
      </SigmaContainer>
      {hover && (
        <div
          data-testid="graph-tooltip"
          className="pointer-events-none absolute z-10 max-w-xs rounded-md border border-line px-3 py-2 text-xs shadow-lg"
          style={{
            left: hover.x + 12,
            top: hover.y + 12,
            background: "#0b1118",
            color: "#e6edf3",
          }}
        >
          <div className="font-mono font-medium">{hover.name}</div>
          <div style={{ color: "#9aa7b4" }}>{hover.meta}</div>
        </div>
      )}
      <div
        data-testid="graph-legend"
        className="pointer-events-none absolute bottom-2 left-2 z-10 flex max-w-[60%] flex-wrap gap-x-3 gap-y-1 rounded-md border border-line px-2.5 py-1.5 text-[0.65rem]"
        style={{ background: "#0b1118cc", color: "#9aa7b4" }}
      >
        {[...new Set(data.nodes.map((n) => n.label ?? "unknown"))]
          .sort()
          .map((k) => (
            <span key={k} className="flex items-center gap-1 font-mono">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{ background: colorForKind(k === "unknown" ? null : k) }}
              />
              {k}
            </span>
          ))}
      </div>
    </div>
  );
}
