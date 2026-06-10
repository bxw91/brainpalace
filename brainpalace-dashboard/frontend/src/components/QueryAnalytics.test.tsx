import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { QueryAnalytics } from "./QueryAnalytics";
import * as client from "../api/client";
import type { QueryStats } from "../api/types";

vi.mock("../api/client");

const stats: QueryStats = {
  total: 42,
  zero_result_count: 3,
  mode_distribution: { hybrid: 30, bm25: 12 },
  latency: { p50: 25, p95: 110, avg: 33 },
  latency_trend: [
    { bucket: "2026-06-10 09:00", count: 20, p50: 22, p95: 90 },
    { bucket: "2026-06-10 10:00", count: 22, p50: 28, p95: 120 },
  ],
  top_queries: [
    { query: "proxy service", count: 9, avg_latency_ms: 21, zero_results: 0, last_ts: 1 },
  ],
  zero_result_queries: [{ query: "ghost feature", count: 3, last_ts: 2 }],
};

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <QueryAnalytics instanceId="i1" since={0} windowKey="24h" />
    </QueryClientProvider>,
  );
}

describe("QueryAnalytics", () => {
  it("renders totals, mode distribution, top + zero-result queries", async () => {
    vi.mocked(client.getQueryStats).mockResolvedValue(stats);
    mount();
    expect(await screen.findByTestId("analytics-total")).toHaveTextContent("42");
    expect(screen.getByTestId("analytics-zero")).toHaveTextContent("3");
    expect(screen.getByTestId("mode-dist-hybrid")).toHaveTextContent("30");
    expect(screen.getByText("proxy service")).toBeInTheDocument();
    expect(screen.getByText("ghost feature")).toBeInTheDocument();
  });
});
