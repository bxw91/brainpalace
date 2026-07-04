import { describe, it, expect, vi } from "vitest";
import { buildExpansion, FAN_OUT } from "./graphExpansion";
import type { GraphSubgraph } from "../api/types";

const node = (id: string) => ({ id, name: id, label: null });
const edge = (a: string, b: string) => ({ id: `${a}-${b}`, source: a, target: b, label: null });
const sub = (nodes: string[], edges: [string, string][]): GraphSubgraph => ({
  nodes: nodes.map(node),
  edges: edges.map(([a, b]) => edge(a, b)),
});

describe("buildExpansion", () => {
  it("expands breadth-first and stops after DEPTH (4) rings", async () => {
    // r-a-b-c-d-e chain: e would be ring 5 → excluded
    const graph: Record<string, GraphSubgraph> = {
      r: sub(["r", "a"], [["r", "a"]]),
      a: sub(["a", "b"], [["a", "b"]]),
      b: sub(["b", "c"], [["b", "c"]]),
      c: sub(["c", "d"], [["c", "d"]]),
      d: sub(["d", "e"], [["d", "e"]]),
    };
    const fetch = vi.fn((id: string) => Promise.resolve(graph[id] ?? sub([], [])));
    const res = await buildExpansion(fetch, "r");
    expect(res.rootId).toBe("r");
    expect(res.nodes.map((n) => n.id).sort()).toEqual(["a", "b", "c", "d", "r"]);
    expect(res.nodes.some((n) => n.id === "e")).toBe(false);
  });

  it("shows ALL direct neighbours of the root (level 1 is uncapped)", async () => {
    const many = Array.from({ length: 20 }, (_, i) => `n${i}`);
    const fetch = vi.fn((id: string) =>
      Promise.resolve(
        id === "r"
          ? sub(["r", ...many], many.map((m) => ["r", m] as [string, string]))
          : sub([], []),
      ),
    );
    const res = await buildExpansion(fetch, "r");
    expect(res.nodes.length).toBe(1 + 20); // root + every direct neighbour, no cap
  });

  it("caps deeper-than-1 levels at FAN_OUT", async () => {
    // r -> h (level 1, uncapped) ; h -> 20 kids (level 2, FAN_OUT-capped).
    const kids = Array.from({ length: 20 }, (_, i) => `k${i}`);
    const graph: Record<string, GraphSubgraph> = {
      r: sub(["r", "h"], [["r", "h"]]),
      h: sub(["h", ...kids], kids.map((k) => ["h", k] as [string, string])),
    };
    const fetch = vi.fn((id: string) => Promise.resolve(graph[id] ?? sub([], [])));
    const res = await buildExpansion(fetch, "r");
    expect(res.nodes.length).toBe(2 + FAN_OUT); // r + h + 8 of h's 20 kids
  });

  it("never exceeds MAX_NODES (300)", async () => {
    // every fetched node yields 50 fresh neighbors → unbounded without the cap
    let counter = 0;
    const fetch = vi.fn((id: string) => {
      const kids = Array.from({ length: 50 }, () => `g${counter++}`);
      return Promise.resolve(sub([id, ...kids], kids.map((k) => [id, k] as [string, string])));
    });
    const res = await buildExpansion(fetch, "r");
    expect(res.nodes.length).toBeLessThanOrEqual(300);
  });

  it("ranks fan-out by true node degree so it picks hubs over leaves", async () => {
    // Root touches FAN_OUT degree-1 leaves plus one real hub. Ranking by the
    // server's `degree` must select the hub (and reach its deep child `x`);
    // the old accumulated-count score would alpha-rank and pick only leaves,
    // stalling at the root's ring. Regression for the ~6-node expansion bug.
    const withDeg = (id: string, degree: number) => ({ id, name: id, label: null, degree });
    // Names sort BEFORE "hub" so the old alpha tiebreak would pick the leaves
    // and drop the hub — the fix must override that on true degree.
    const leaves = Array.from({ length: FAN_OUT }, (_, i) => `aleaf${i}`);
    const graph: Record<string, GraphSubgraph> = {
      r: {
        nodes: [withDeg("r", FAN_OUT + 1), withDeg("hub", 99), ...leaves.map((l) => withDeg(l, 1))],
        edges: [["r", "hub"], ...leaves.map((l) => ["r", l] as [string, string])].map(([a, b]) =>
          edge(a, b),
        ),
      },
      hub: { nodes: [withDeg("hub", 99), withDeg("x", 1)], edges: [edge("hub", "x")] },
    };
    const fetch = vi.fn((id: string) => Promise.resolve(graph[id] ?? sub([], [])));
    const res = await buildExpansion(fetch, "r");
    const ids = res.nodes.map((n) => n.id);
    expect(ids).toContain("hub");
    expect(ids).toContain("x"); // reached only because the hub was selected
  });

  it("merges same-name siblings so callers attached to a sibling appear", async () => {
    // `sym` only contains its member; the caller edge lives on the sibling
    // `./sym` (extraction split the concept). Seeding the sibling as a co-root
    // must surface the caller.
    const graph: Record<string, GraphSubgraph> = {
      sym: sub(["sym", "child"], [["sym", "child"]]),
      "./sym": sub(["./sym", "caller"], [["caller", "./sym"]]),
    };
    const fetch = vi.fn((id: string) => Promise.resolve(graph[id] ?? sub([], [])));
    const resolveSiblings = vi.fn(async (name: string) =>
      name === "sym" ? ["./sym"] : [],
    );
    const res = await buildExpansion(fetch, "sym", resolveSiblings);
    const ids = res.nodes.map((n) => n.id);
    expect(ids).toContain("./sym");
    expect(ids).toContain("caller"); // reached only via the merged sibling
  });

  it("keeps only nodes whose endpoints are both retained", async () => {
    const fetch = vi.fn(() => Promise.resolve(sub([], [])));
    const res = await buildExpansion(fetch, "lonely");
    expect(res.nodes.map((n) => n.id)).toEqual(["lonely"]); // root always present
    expect(res.edges).toEqual([]);
  });
});
