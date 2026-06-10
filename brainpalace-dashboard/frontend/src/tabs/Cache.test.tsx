import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Cache } from "./Cache";
import { ToastProvider } from "../components/Toast";
import * as client from "../api/client";
import type { CachePayload } from "../api/types";

vi.mock("../api/client");

const cache: CachePayload = {
  hits: 41,
  misses: 9,
  hit_rate: 0.82,
  mem_entries: 48,
  entry_count: 6567,
  size_bytes: 85069824,
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
  vi.mocked(client.getCache).mockResolvedValue(cache);
  vi.mocked(client.clearCache).mockResolvedValue({ ok: true });
  vi.mocked(client.getCacheHistory).mockResolvedValue({ snapshots: [] });
  vi.mocked(client.getCacheEconomics).mockResolvedValue({
    provider: "openai",
    model: "text-embedding-3-small",
    price_usd_per_mtok: 0.02,
    avg_tokens_per_chunk: 400,
    session_hits: 0,
    session_misses: 0,
    est_spend_usd: 0,
    est_saved_usd: 0,
    cached_entries: 0,
    est_reindex_cost_usd: 0,
  });
});

describe("Cache tab", () => {
  it("renders the hit-rate gauge and stats", async () => {
    wrap(<Cache instanceId="a" />);
    const gauge = await screen.findByTestId("hit-rate-gauge");
    expect(gauge).toHaveAttribute("data-rate", "82");
    expect(screen.getByTestId("stat-cache-entries")).toBeInTheDocument();
    expect(within(screen.getByTestId("stat-cache-hits")).getByText("41")).toBeInTheDocument();
  });

  it("Clear cache is confirm-gated then calls clearCache", async () => {
    wrap(<Cache instanceId="a" />);
    await screen.findByTestId("hit-rate-gauge");
    fireEvent.click(screen.getByTestId("btn-clear-cache"));
    const dialog = await screen.findByTestId("confirm-dialog");
    fireEvent.click(within(dialog).getByTestId("btn-confirm"));
    await waitFor(() => expect(client.clearCache).toHaveBeenCalledWith("a"));
  });

  it("shows stopped state when unreachable", async () => {
    vi.mocked(client.getCache).mockRejectedValue(
      new client.InstanceUnreachableError("down", 502),
    );
    wrap(<Cache instanceId="a" />);
    expect(await screen.findByTestId("cache-stopped")).toBeInTheDocument();
  });

  it("shows a loading skeleton while the cache query is pending", () => {
    let resolve!: (v: CachePayload) => void;
    vi.mocked(client.getCache).mockReturnValue(
      new Promise<CachePayload>((r) => {
        resolve = r;
      }),
    );
    wrap(<Cache instanceId="a" />);
    expect(screen.getByTestId("tab-cache")).toBeInTheDocument();
    expect(document.querySelector(".skeleton")).toBeTruthy();
    resolve(cache);
  });

  it("renders the hit-rate trend chart and economics panel", async () => {
    vi.mocked(client.getCacheHistory).mockResolvedValue({
      snapshots: [
        { ts: 1765400400, hits: 0, misses: 0, entry_count: 0, size_bytes: 0 },
        { ts: 1765400700, hits: 3, misses: 1, entry_count: 4, size_bytes: 100 },
        { ts: 1765401000, hits: 9, misses: 1, entry_count: 10, size_bytes: 200 },
      ],
    });
    vi.mocked(client.getCacheEconomics).mockResolvedValue({
      provider: "openai",
      model: "text-embedding-3-small",
      price_usd_per_mtok: 0.02,
      avg_tokens_per_chunk: 400,
      session_hits: 9,
      session_misses: 1,
      est_spend_usd: 0.01,
      est_saved_usd: 0.07,
      cached_entries: 10,
      est_reindex_cost_usd: 0.08,
    });
    wrap(<Cache instanceId="a" />);
    expect(await screen.findByTestId("rate-chart")).toBeInTheDocument();
    expect(await screen.findByTestId("cache-economics")).toBeInTheDocument();
  });

  it("shows an error state with retry on a non-unreachable failure", async () => {
    vi.mocked(client.getCache).mockRejectedValue(new Error("kaboom"));
    wrap(<Cache instanceId="a" />);
    const err = await screen.findByTestId("cache-error");
    expect(within(err).getByText(/kaboom/)).toBeInTheDocument();
    expect(screen.getByTestId("cache-error-retry")).toBeInTheDocument();
  });
});
