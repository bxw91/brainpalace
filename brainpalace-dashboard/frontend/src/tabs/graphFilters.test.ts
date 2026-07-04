import { describe, expect, it } from "vitest";
import { filterSubgraph } from "./graphFilters";
import type { Expansion } from "./graphExpansion";

const sub: Expansion = {
  rootId: "a",
  nodes: [
    { id: "a", name: "a", label: "Function" },
    { id: "b", name: "b", label: "Folder" },
    { id: "c", name: "c", label: "Class" },
  ],
  edges: [
    { id: "e1", source: "a", target: "b", label: "contains" },
    { id: "e2", source: "a", target: "c", label: "calls" },
    { id: "e3", source: "c", target: "a", label: "references" },
  ],
};

describe("filterSubgraph", () => {
  it("passes through with nothing hidden", () => {
    const out = filterSubgraph(sub, new Set(), new Set());
    expect(out.nodes).toHaveLength(3);
    expect(out.edges).toHaveLength(3);
  });
  it("drops hidden kinds and their edges", () => {
    const out = filterSubgraph(sub, new Set(["Folder"]), new Set());
    expect(out.nodes.map((n) => n.id)).toEqual(["a", "c"]);
    expect(out.edges.map((e) => e.id)).toEqual(["e2", "e3"]);
  });
  it("drops hidden edge types but keeps nodes", () => {
    const out = filterSubgraph(sub, new Set(), new Set(["calls"]));
    expect(out.nodes).toHaveLength(3);
    expect(out.edges.map((e) => e.id)).toEqual(["e1", "e3"]);
  });
  it("never drops the root", () => {
    const out = filterSubgraph(sub, new Set(["Function"]), new Set());
    expect(out.nodes.some((n) => n.id === "a")).toBe(true);
  });
});
