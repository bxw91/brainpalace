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
  vi.mocked(client.getQueryStats).mockResolvedValue({
    total: 0,
    zero_result_count: 0,
    mode_distribution: {},
    latency: { p50: 0, p95: 0, avg: 0 },
    latency_trend: [],
    top_queries: [],
    zero_result_queries: [],
  });
});

describe("Queries tab", () => {
  it("renders history rows", async () => {
    wrap(<Queries instanceId="a" />);
    expect(await screen.findByText("how does the proxy work")).toBeInTheDocument();
    expect(screen.getByText("embedding cache eviction")).toBeInTheDocument();
  });

  it("default range is 24h", async () => {
    wrap(<Queries instanceId="a" />);
    await screen.findByText("how does the proxy work");
    const sinceArg = vi.mocked(client.getQueries).mock.calls[0][1]?.since;
    expect(sinceArg).toBeDefined();
    const ageDays = (now - (sinceArg as number)) / 86400;
    expect(ageDays).toBeGreaterThanOrEqual(0.9);
    expect(ageDays).toBeLessThanOrEqual(1.1);
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

describe("retrieval explorer", () => {
  it("compare run fires one replay per mode and renders 4 columns", async () => {
    vi.mocked(client.getQueries).mockResolvedValue(rows);
    vi.mocked(client.replayQuery).mockResolvedValue(replay);
    wrap(<Queries instanceId="a" />);
    fireEvent.click(await screen.findByTestId("btn-new-query"));
    fireEvent.click(screen.getByTestId("toggle-compare"));
    fireEvent.change(screen.getByTestId("input-run-query"), {
      target: { value: "proxy" },
    });
    fireEvent.click(screen.getByTestId("btn-run-query"));
    await waitFor(() =>
      expect(client.replayQuery).toHaveBeenCalledTimes(4),
    );
    const modes = vi
      .mocked(client.replayQuery)
      .mock.calls.map(([, body]) => body.mode)
      .sort();
    expect(modes).toEqual(["bm25", "graph", "hybrid", "vector"]);
    expect(await screen.findByTestId("compare-grid")).toBeInTheDocument();
    expect(screen.getByTestId("compare-col-bm25")).toBeInTheDocument();
  });

  it("reranker select forwards the override flag", async () => {
    vi.mocked(client.getQueries).mockResolvedValue(rows);
    vi.mocked(client.replayQuery).mockResolvedValue(replay);
    wrap(<Queries instanceId="a" />);
    fireEvent.click(await screen.findByTestId("btn-new-query"));
    fireEvent.change(screen.getByTestId("select-rerank"), {
      target: { value: "off" },
    });
    fireEvent.change(screen.getByTestId("input-run-query"), {
      target: { value: "proxy" },
    });
    fireEvent.click(screen.getByTestId("btn-run-query"));
    await waitFor(() => expect(client.replayQuery).toHaveBeenCalled());
    const [, body] = vi.mocked(client.replayQuery).mock.calls[0];
    expect(body.rerank).toBe(false);
  });

  it("offers compute and scan run modes", async () => {
    wrap(<Queries instanceId="a" />);
    fireEvent.click(await screen.findByTestId("btn-new-query"));
    const options = within(screen.getByTestId("select-run-mode"))
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).value);
    expect(options).toEqual(expect.arrayContaining(["compute", "scan"]));
  });

  it("offers the absence run mode", async () => {
    wrap(<Queries instanceId="a" />);
    fireEvent.click(await screen.findByTestId("btn-new-query"));
    const options = within(screen.getByTestId("select-run-mode"))
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).value);
    expect(options).toEqual(expect.arrayContaining(["absence"]));
  });

  it("renders absence rows as 'in X, not Y' lines", async () => {
    vi.mocked(client.replayQuery).mockResolvedValue({
      results: [],
      query_time_ms: 2,
      total_results: 1,
      absence: [{ label: "walk", present_in: "distance", absent_from: "duration" }],
    });
    wrap(<Queries instanceId="a" />);
    fireEvent.click(await screen.findByTestId("btn-new-query"));
    fireEvent.change(screen.getByTestId("select-run-mode"), {
      target: { value: "absence" },
    });
    fireEvent.change(screen.getByTestId("input-run-query"), {
      target: { value: "subjects with distance but not duration" },
    });
    fireEvent.click(screen.getByTestId("btn-run-query"));
    expect(
      await screen.findByText("walk (in distance, not duration)"),
    ).toBeInTheDocument();
  });

  it("offers the timeline run mode", async () => {
    wrap(<Queries instanceId="a" />);
    fireEvent.click(await screen.findByTestId("btn-new-query"));
    const options = within(screen.getByTestId("select-run-mode"))
      .getAllByRole("option")
      .map((o) => (o as HTMLOptionElement).value);
    expect(options).toEqual(expect.arrayContaining(["timeline"]));
  });

  it("renders timeline rows as edge-history lines", async () => {
    vi.mocked(client.replayQuery).mockResolvedValue({
      results: [],
      query_time_ms: 3,
      total_results: 1,
      timeline: [
        {
          subject: "d1",
          predicate: "superseded-by",
          object: "d2",
          valid_from: "2026-03-01T00:00:00",
          valid_until: null,
          valid: true,
        },
      ],
    });
    wrap(<Queries instanceId="a" />);
    fireEvent.click(await screen.findByTestId("btn-new-query"));
    fireEvent.change(screen.getByTestId("select-run-mode"), {
      target: { value: "timeline" },
    });
    fireEvent.change(screen.getByTestId("input-run-query"), {
      target: { value: "how did d1 evolve" },
    });
    fireEvent.click(screen.getByTestId("btn-run-query"));
    expect(
      await screen.findByText(/d1 —superseded-by→ d2/),
    ).toBeInTheDocument();
  });

  it("renders scan rows as label: value lines", async () => {
    vi.mocked(client.replayQuery).mockResolvedValue({
      results: [],
      query_time_ms: 2,
      total_results: 1,
      scan: [{ label: "2026-W03", value: 3 }],
    });
    wrap(<Queries instanceId="a" />);
    fireEvent.click(await screen.findByTestId("btn-new-query"));
    fireEvent.change(screen.getByTestId("select-run-mode"), {
      target: { value: "scan" },
    });
    fireEvent.change(screen.getByTestId("input-run-query"), {
      target: { value: "which week did I mention foobar most" },
    });
    fireEvent.click(screen.getByTestId("btn-run-query"));
    expect(await screen.findByText("2026-W03: 3")).toBeInTheDocument();
  });
});
