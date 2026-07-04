import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Graph } from "./Graph";
import { ToastProvider } from "../components/Toast";
import * as client from "../api/client";

vi.mock("../api/client");

vi.mock("../components/GraphCanvas", () => ({
  default: ({
    data,
    onNodeClick,
  }: {
    data: { nodes: Array<{ id: string; name: string }> };
    onNodeClick: (id: string) => void;
  }) => (
    <div data-testid="graph-canvas-stub">
      {data.nodes.length} nodes
      {data.nodes.map((n) => (
        <button
          key={n.id}
          type="button"
          data-testid={`canvas-node-${n.id}`}
          onClick={() => onNodeClick(n.id)}
        >
          {n.name}
        </button>
      ))}
    </div>
  ),
}));

const status = {
  graph_index: {
    enabled: true,
    initialized: true,
    entity_count: 3028,
    relationship_count: 5463,
    store_type: "sqlite",
  },
  git_commits: 1004,
};

function wrap(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(client.getInstanceStatus).mockResolvedValue(status as never);
  vi.mocked(client.gitReindex).mockResolvedValue({ ok: true });
});

describe("Graph tab", () => {
  it("renders entity / relationship / store cards", async () => {
    wrap(<Graph instanceId="a" />);
    expect(
      within(await screen.findByTestId("stat-graph-entities")).getByText(/3,028|3028/),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("stat-graph-rels")).getByText(/5,463|5463/),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("stat-graph-store")).getByText(/sqlite/i),
    ).toBeInTheDocument();
  });

  it("Re-index git history is confirm-gated then calls gitReindex", async () => {
    wrap(<Graph instanceId="a" />);
    await screen.findByTestId("stat-graph-entities");
    fireEvent.click(screen.getByTestId("btn-git-reindex"));
    const dialog = await screen.findByTestId("confirm-dialog");
    fireEvent.click(within(dialog).getByTestId("btn-confirm"));
    await waitFor(() => expect(client.gitReindex).toHaveBeenCalledWith("a"));
  });

  it("shows stopped state when unreachable", async () => {
    vi.mocked(client.getInstanceStatus).mockRejectedValue(
      new client.InstanceUnreachableError("down", 502),
    );
    wrap(<Graph instanceId="a" />);
    expect(await screen.findByTestId("graph-stopped")).toBeInTheDocument();
  });

  it("shows an error state with retry on a non-unreachable failure", async () => {
    vi.mocked(client.getInstanceStatus).mockRejectedValue(new Error("graph 500"));
    wrap(<Graph instanceId="a" />);
    const err = await screen.findByTestId("graph-error");
    expect(within(err).getByText(/graph 500/)).toBeInTheDocument();
    expect(screen.getByTestId("graph-error-retry")).toBeInTheDocument();
  });
});

describe("graph browser", () => {
  it("shows error message when searchGraphNodes rejects", async () => {
    vi.mocked(client.searchGraphNodes).mockRejectedValue(new Error("boom"));
    wrap(<Graph instanceId="a" />);
    fireEvent.change(await screen.findByTestId("input-graph-search"), {
      target: { value: "query" },
    });
    fireEvent.click(screen.getByTestId("btn-graph-search"));
    expect(await screen.findByText(/boom/)).toBeInTheDocument();
  });

  it("Start opens the hub panel and auto-roots the #1 hub", async () => {
    vi.mocked(client.getGraphTopNodes).mockResolvedValue({
      nodes: [
        { id: "hub", name: "QueryService", label: "Class", degree: 12 },
        { id: "n2", name: "execute_query", label: "Function", degree: 4 },
      ],
    });
    vi.mocked(client.getGraphNeighbors).mockResolvedValue({
      nodes: [
        { id: "hub", name: "QueryService", label: "Class" },
        { id: "n3", name: "Cache", label: "Class" },
      ],
      edges: [{ id: "e1", source: "hub", target: "n3", label: "uses" }],
    });
    wrap(<Graph instanceId="a" />);
    fireEvent.click(await screen.findByTestId("btn-graph-start"));
    // Panel opens with the hubs; canvas lands rooted on the #1 hub.
    expect(await screen.findByTestId("graph-search-panel")).toBeInTheDocument();
    expect(await screen.findByTestId("graph-canvas-stub")).toHaveTextContent("2 nodes");
    expect(client.getGraphTopNodes).toHaveBeenCalledWith("a", 15, ["code"]);
    // BFS expands the root via per-node neighbor requests.
    expect(client.getGraphNeighbors).toHaveBeenCalledWith("a", "hub", 200, ["code"]);
    expect(screen.getByTestId("btn-explore-n2")).toBeInTheDocument();
    // Re-rooting also looks up same-name sibling nodes to merge in callers.
    expect(client.searchGraphNodes).toHaveBeenCalledWith("a", "QueryService", 50, ["code"]);
  });

  it("searching opens the results panel; picking a row re-roots and closes it", async () => {
    vi.mocked(client.searchGraphNodes).mockResolvedValue({
      nodes: [{ id: "n1", name: "QueryService", label: "Class", degree: 3 }],
    });
    vi.mocked(client.getGraphNeighbors).mockResolvedValue({
      nodes: [
        { id: "n1", name: "QueryService", label: "Class" },
        { id: "n2", name: "execute_query", label: "Function" },
      ],
      edges: [{ id: "e1", source: "n1", target: "n2", label: "contains" }],
    });
    wrap(<Graph instanceId="a" />);
    fireEvent.change(await screen.findByTestId("input-graph-search"), {
      target: { value: "query" },
    });
    fireEvent.click(screen.getByTestId("btn-graph-search"));
    fireEvent.click(await screen.findByTestId("btn-explore-n1"));
    // Canvas re-roots on the picked node …
    expect(await screen.findByTestId("graph-canvas-stub")).toHaveTextContent("2 nodes");
    expect(client.getGraphNeighbors).toHaveBeenCalledWith("a", "n1", 200, ["code"]);
    // … and the panel closes after the pick.
    await waitFor(() =>
      expect(screen.queryByTestId("graph-search-panel")).not.toBeInTheDocument(),
    );
  });

  it("backdrop click closes the panel", async () => {
    vi.mocked(client.searchGraphNodes).mockResolvedValue({
      nodes: [{ id: "n1", name: "QueryService", label: "Class", degree: 3 }],
    });
    wrap(<Graph instanceId="a" />);
    fireEvent.change(await screen.findByTestId("input-graph-search"), {
      target: { value: "query" },
    });
    fireEvent.click(screen.getByTestId("btn-graph-search"));
    await screen.findByTestId("graph-search-panel");
    fireEvent.click(screen.getByTestId("graph-panel-backdrop"));
    await waitFor(() =>
      expect(screen.queryByTestId("graph-search-panel")).not.toBeInTheDocument(),
    );
  });
});

describe("node detail panel", () => {
  it("opens the panel on node click instead of re-rooting", async () => {
    vi.mocked(client.getGraphTopNodes).mockResolvedValue({
      nodes: [{ id: "hub", name: "QueryService", label: "Class", degree: 2 }],
    });
    vi.mocked(client.getGraphNeighbors).mockResolvedValue({
      nodes: [
        { id: "hub", name: "QueryService", label: "Class" },
        {
          id: "b",
          name: "execute_query",
          label: "Function",
          properties: { path: "/repo/b.py", line: 3 },
        },
      ],
      edges: [{ id: "e1", source: "hub", target: "b", label: "calls" }],
    });
    wrap(<Graph instanceId="a" />);
    fireEvent.click(await screen.findByTestId("btn-graph-start"));
    await screen.findByTestId("canvas-node-b");
    const callsBeforeClick = vi.mocked(client.getGraphNeighbors).mock.calls.length;

    await userEvent.click(screen.getByTestId("canvas-node-b"));

    expect(await screen.findByTestId("graph-node-panel")).toBeInTheDocument();
    expect(screen.getByTestId("node-panel-file")).toHaveTextContent("b.py:4");
    // Opening the panel must NOT trigger a new expansion (no reroot on click).
    const callsAfterOpen = vi.mocked(client.getGraphNeighbors).mock.calls.length;
    expect(callsAfterOpen).toBe(callsBeforeClick);
  });

  it("re-roots from the panel button", async () => {
    vi.mocked(client.getGraphTopNodes).mockResolvedValue({
      nodes: [{ id: "hub", name: "QueryService", label: "Class", degree: 2 }],
    });
    vi.mocked(client.getGraphNeighbors).mockResolvedValue({
      nodes: [
        { id: "hub", name: "QueryService", label: "Class" },
        { id: "b", name: "execute_query", label: "Function" },
      ],
      edges: [{ id: "e1", source: "hub", target: "b", label: "calls" }],
    });
    wrap(<Graph instanceId="a" />);
    fireEvent.click(await screen.findByTestId("btn-graph-start"));
    await userEvent.click(await screen.findByTestId("canvas-node-b"));
    await screen.findByTestId("graph-node-panel");

    await userEvent.click(screen.getByTestId("btn-node-reroot"));

    await waitFor(() =>
      expect(vi.mocked(client.getGraphNeighbors)).toHaveBeenCalledWith(
        expect.anything(), "b", expect.anything(), expect.anything(),
      ),
    );
  });

  it("lists callers/callees from the current subgraph and fetches the snippet", async () => {
    vi.mocked(client.getGraphTopNodes).mockResolvedValue({
      nodes: [{ id: "a", name: "Root", label: "Class", degree: 2 }],
    });
    vi.mocked(client.getGraphNeighbors).mockResolvedValue({
      nodes: [
        { id: "a", name: "Root", label: "Class" },
        { id: "b", name: "Middle", label: "Function" },
        { id: "c", name: "Leaf", label: "Function" },
      ],
      edges: [
        { id: "e1", source: "a", target: "b", label: "calls" },
        { id: "e2", source: "b", target: "c", label: "imports" },
      ],
    });
    vi.mocked(client.getGraphNodeSource).mockResolvedValue({
      path: "/repo/b.py",
      line: 3,
      start_line: 1,
      lines: ["x", "y", "z"],
    });
    wrap(<Graph instanceId="a" />);
    fireEvent.click(await screen.findByTestId("btn-graph-start"));
    await userEvent.click(await screen.findByTestId("canvas-node-b"));
    await screen.findByTestId("graph-node-panel");

    expect(screen.getByTestId("node-panel-in")).toHaveTextContent("Root");
    expect(screen.getByTestId("node-panel-out")).toHaveTextContent("Leaf");
    expect(await screen.findByTestId("node-panel-snippet")).toHaveTextContent("y");
  });
});
