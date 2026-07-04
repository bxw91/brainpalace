import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { NodeDetailPanel } from "./NodeDetailPanel";

vi.mock("../api/client", () => ({
  getGraphNodeSource: vi.fn().mockRejectedValue(new Error("no source")),
  getGraphImpact: vi.fn().mockResolvedValue({
    node: "lib.py:helper",
    nodes: [
      {
        id: "api.py:handler",
        name: "handler",
        label: "Function",
        domain: "code",
        depth: 1,
        via_predicate: "calls",
        via_node_id: "lib.py:helper",
      },
    ],
  }),
  getGraphCochange: vi.fn().mockResolvedValue({
    node: "lib.py:helper",
    files: [{ file_id: "/p/api.py", name: "api.py", shared_commits: 4 }],
  }),
}));

const node = {
  id: "lib.py:helper",
  name: "helper",
  label: "Function",
  domain: "code",
  degree: 2,
  properties: {},
};

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <NodeDetailPanel
        instanceId="i1"
        node={node}
        edges={[]}
        nodesById={new Map([[node.id, node]])}
        onReroot={() => {}}
        onSelect={() => {}}
        onClose={() => {}}
      />
    </QueryClientProvider>,
  );
}

describe("NodeDetailPanel query power sections", () => {
  it("renders impact dependents with depth and predicate", async () => {
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId("node-panel-impact")).toHaveTextContent("handler"),
    );
    expect(screen.getByTestId("node-panel-impact")).toHaveTextContent("calls");
  });

  it("renders co-change files with shared-commit counts", async () => {
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId("node-panel-cochange")).toHaveTextContent("api.py"),
    );
    expect(screen.getByTestId("node-panel-cochange")).toHaveTextContent("4");
  });
});
