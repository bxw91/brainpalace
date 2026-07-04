import { describe, it, expect } from "vitest";
import {
  computeConcentricLayout,
  formatNodeTooltip,
  RING_RADIUS,
  KIND_COLORS,
  colorForKind,
  FALLBACK_KIND_COLOR,
  nodeFile,
} from "./graphLayout";
import type { GraphSubgraph } from "../api/types";

const n = (id: string, label: string | null = null) => ({ id, name: id, label });
const e = (id: string, source: string, target: string) => ({ id, source, target, label: null });

describe("computeConcentricLayout", () => {
  it("places root at center and assigns BFS rings", () => {
    const data: GraphSubgraph = {
      nodes: [n("r"), n("a"), n("b"), n("c")],
      edges: [e("e1", "r", "a"), e("e2", "r", "b"), e("e3", "a", "c")],
    };
    const p = computeConcentricLayout(data, "r");
    expect(p.get("r")).toMatchObject({ x: 0, y: 0, ring: 0 });
    expect(p.get("a")!.ring).toBe(1);
    expect(p.get("b")!.ring).toBe(1);
    expect(p.get("c")!.ring).toBe(2);
    expect(Math.hypot(p.get("a")!.x, p.get("a")!.y)).toBeCloseTo(RING_RADIUS);
    expect(Math.hypot(p.get("c")!.x, p.get("c")!.y)).toBeCloseTo(2 * RING_RADIUS);
  });

  it("puts nodes unreachable from root beyond the outermost ring", () => {
    const data: GraphSubgraph = { nodes: [n("r"), n("x")], edges: [] };
    const p = computeConcentricLayout(data, "r");
    expect(p.get("x")!.ring).toBe(1); // maxRing(0) + 1
  });
});

describe("formatNodeTooltip", () => {
  it("renders name and a meta line with type, degree, level", () => {
    const t = formatNodeTooltip({ name: "QueryService", label: "Class" }, 2, 7);
    expect(t.name).toBe("QueryService");
    expect(t.meta).toBe("Class · degree 7 · level 2");
  });
  it("falls back to 'unknown' when label is null", () => {
    expect(formatNodeTooltip({ name: "x", label: null }, 0, 0).meta).toContain("unknown");
  });
});

describe("kind colors", () => {
  it("has a distinct color for the live code kinds", () => {
    const kinds = ["File", "Folder", "Class", "Method", "Function",
      "Interface", "Enum", "Module", "Package", "Decorator", "Endpoint"];
    const seen = new Set(kinds.map((k) => KIND_COLORS[k]));
    expect(seen.size).toBe(kinds.length); // no collisions among code kinds
  });
  it("falls back for unknown kinds", () => {
    expect(colorForKind("Zorp")).toBe(FALLBACK_KIND_COLOR);
    expect(colorForKind(null)).toBe(FALLBACK_KIND_COLOR);
  });
});

describe("nodeFile", () => {
  it("prefers properties.path", () => {
    expect(nodeFile({ id: "x", properties: { path: "/a/b.py", line: 3 } }))
      .toBe("/a/b.py");
  });
  it("derives from a symbol id", () => {
    expect(nodeFile({ id: "/a/b.py:C.m" })).toBe("/a/b.py");
  });
  it("returns null for non-path ids", () => {
    expect(nodeFile({ id: "decorator:app.get" })).toBe(null);
    expect(nodeFile({ id: "requests" })).toBe(null);
  });
});

describe("formatNodeTooltip file row", () => {
  it("includes the file basename when known", () => {
    const t = formatNodeTooltip(
      { name: "m", label: "Method", id: "/a/b.py:C.m" } as never, 1, 4,
    );
    expect(t.meta).toContain("b.py");
  });
});
