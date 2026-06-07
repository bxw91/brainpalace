import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Queries } from "./Queries";
import { ToastProvider } from "../components/Toast";
import * as client from "../api/client";
import type { QueryRow, QueryDetail, ReplayResponse } from "../api/types";

vi.mock("../api/client");

const now = Date.now() / 1000;
const rows: QueryRow[] = [
  {
    id: "q1",
    ts: now - 60,
    mode: "hybrid",
    query: "how does the proxy work",
    top_k: 5,
    latency_ms: 42,
    result_count: 5,
    alpha: 0.5,
  },
  {
    id: "q2",
    ts: now - 3600 * 30, // > 1 day ago
    mode: "vector",
    query: "embedding cache eviction",
    top_k: 8,
    latency_ms: 88,
    result_count: 8,
    alpha: null,
  },
];

const detail: QueryDetail = {
  ...rows[0],
  filters: { source_types: ["code"], languages: ["python"] },
  results: [
    { score: 0.91, path: "/repo/proxy.py", lines: [10, 40], snippet: "class ProxyService" },
  ],
};

const replay: ReplayResponse = {
  query_time_ms: 12,
  total_results: 1,
  results: [
    {
      text: "fresh snippet",
      source: "/repo/proxy.py",
      score: 0.95,
      chunk_id: "c1",
      source_type: "code",
      language: "python",
    },
  ],
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
  vi.mocked(client.getQueries).mockResolvedValue(rows);
  vi.mocked(client.getQueryDetail).mockResolvedValue(detail);
  vi.mocked(client.replayQuery).mockResolvedValue(replay);
});

describe("Queries tab", () => {
  it("renders history rows", async () => {
    wrap(<Queries instanceId="a" />);
    expect(await screen.findByText("how does the proxy work")).toBeInTheDocument();
    expect(screen.getByText("embedding cache eviction")).toBeInTheDocument();
  });

  it("default range spans at least 2 days", async () => {
    wrap(<Queries instanceId="a" />);
    await screen.findByText("how does the proxy work");
    const sinceArg = vi.mocked(client.getQueries).mock.calls[0][1]?.since;
    expect(sinceArg).toBeDefined();
    const ageDays = (now - (sinceArg as number)) / 86400;
    expect(ageDays).toBeGreaterThanOrEqual(2);
  });

  it("mode filter re-queries with {mode}", async () => {
    wrap(<Queries instanceId="a" />);
    await screen.findByText("how does the proxy work");
    fireEvent.change(screen.getByTestId("select-mode"), {
      target: { value: "vector" },
    });
    await waitFor(() => {
      const calls = vi.mocked(client.getQueries).mock.calls;
      const lastCall = calls[calls.length - 1];
      expect(lastCall?.[1]?.mode).toBe("vector");
    });
  });

  it("clicking a row opens the drawer with ranked results", async () => {
    wrap(<Queries instanceId="a" />);
    await screen.findByText("how does the proxy work");
    fireEvent.click(screen.getByTestId("query-row-q1"));
    const drawer = await screen.findByTestId("query-drawer");
    expect(await within(drawer).findByText(/proxy.py/)).toBeInTheDocument();
  });

  it("Re-run replays and shows fresh results", async () => {
    wrap(<Queries instanceId="a" />);
    await screen.findByText("how does the proxy work");
    fireEvent.click(screen.getByTestId("query-row-q1"));
    const drawer = await screen.findByTestId("query-drawer");
    fireEvent.click(within(drawer).getByTestId("btn-rerun"));
    await waitFor(() =>
      expect(client.replayQuery).toHaveBeenCalledWith("a", {
        query: "how does the proxy work",
        mode: "hybrid",
        top_k: 5,
      }),
    );
    expect(await within(drawer).findByTestId("replay-results")).toBeInTheDocument();
    expect(within(drawer).getByText("fresh snippet")).toBeInTheDocument();
  });

  it("renders the latency chart", async () => {
    wrap(<Queries instanceId="a" />);
    await screen.findByText("how does the proxy work");
    expect(screen.getByTestId("latency-chart")).toBeInTheDocument();
  });

  it("shows the stopped state when unreachable", async () => {
    vi.mocked(client.getQueries).mockRejectedValue(
      new client.InstanceUnreachableError("down", 502),
    );
    wrap(<Queries instanceId="a" />);
    expect(await screen.findByTestId("queries-stopped")).toBeInTheDocument();
  });

  it("shows an error state with retry on a non-unreachable failure", async () => {
    vi.mocked(client.getQueries).mockRejectedValue(new Error("history 500"));
    wrap(<Queries instanceId="a" />);
    const err = await screen.findByTestId("queries-error");
    expect(within(err).getByText(/history 500/)).toBeInTheDocument();
    expect(screen.getByTestId("queries-error-retry")).toBeInTheDocument();
  });

  it("shows the empty state when no queries are logged in the window", async () => {
    vi.mocked(client.getQueries).mockResolvedValue([]);
    wrap(<Queries instanceId="a" />);
    expect(
      await screen.findByText(/no queries logged in this window/i),
    ).toBeInTheDocument();
  });

  it("runs a new query from the composer and refreshes history", async () => {
    wrap(<Queries instanceId="a" />);
    await screen.findByText("how does the proxy work");
    fireEvent.click(screen.getByTestId("btn-new-query"));
    fireEvent.change(screen.getByTestId("input-run-query"), {
      target: { value: "hello" },
    });
    fireEvent.click(screen.getByTestId("btn-run-query"));
    await waitFor(() =>
      expect(client.replayQuery).toHaveBeenCalledWith("a", {
        query: "hello",
        mode: "hybrid",
        top_k: 5,
      }),
    );
    expect(await screen.findByTestId("run-results")).toBeInTheDocument();
  });
});
