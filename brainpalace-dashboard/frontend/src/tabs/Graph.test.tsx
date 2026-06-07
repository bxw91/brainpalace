import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Graph } from "./Graph";
import { ToastProvider } from "../components/Toast";
import * as client from "../api/client";

vi.mock("../api/client");

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
