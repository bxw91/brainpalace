import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Graph } from "./Graph";
import { ToastProvider } from "../components/Toast";
import * as client from "../api/client";

vi.mock("../api/client");

vi.mock("../components/GraphCanvas", () => ({
  default: ({ data }: { data: { nodes: unknown[] } }) => (
    <div data-testid="graph-canvas-stub">{data.nodes.length} nodes</div>
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

  it("Start graph browser seeds top hubs and auto-expands the most-connected one", async () => {
    vi.mocked(client.getGraphTopNodes).mockResolvedValue({
      nodes: [
        { id: "hub", name: "QueryService", label: "Class", degree: 12 },
        { id: "n2", name: "execute_query", label: "Function", degree: 4 },
      ],
    });
    vi.mocked(client.getGraphNeighbors).mockResolvedValue({
      nodes: [
        { id: "hub", name: "QueryService", label: "Class" },
        { id: "n2", name: "execute_query", label: "Function" },
        { id: "n3", name: "Cache", label: "Class" },
      ],
      edges: [{ id: "e1", source: "hub", target: "n3", label: "uses" }],
    });
    wrap(<Graph instanceId="a" />);
    fireEvent.click(await screen.findByTestId("btn-graph-start"));
    // Canvas opens auto-expanded on the #1 hub (no search performed).
    expect(await screen.findByTestId("graph-canvas-stub")).toHaveTextContent(
      "3 nodes",
    );
    expect(client.getGraphTopNodes).toHaveBeenCalledWith("a", 15);
    expect(client.getGraphNeighbors).toHaveBeenCalledWith("a", "hub", 200);
    // The other hub is offered as an alternative seed.
    expect(screen.getByTestId("btn-explore-n2")).toBeInTheDocument();
    expect(client.searchGraphNodes).not.toHaveBeenCalled();
  });

  it("searches seeds and opens the canvas on Explore", async () => {
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
    expect(await screen.findByTestId("graph-canvas-stub")).toHaveTextContent(
      "2 nodes",
    );
    expect(client.getGraphNeighbors).toHaveBeenCalledWith("a", "n1", 200);
  });
});
