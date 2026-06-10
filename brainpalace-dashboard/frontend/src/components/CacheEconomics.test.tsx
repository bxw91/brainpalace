import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CacheEconomicsPanel } from "./CacheEconomics";
import * as client from "../api/client";
import type { CacheEconomics } from "../api/types";

vi.mock("../api/client");

const econ: CacheEconomics = {
  provider: "openai",
  model: "text-embedding-3-small",
  price_usd_per_mtok: 0.02,
  avg_tokens_per_chunk: 400,
  session_hits: 5000,
  session_misses: 1000,
  est_spend_usd: 0.008,
  est_saved_usd: 0.04,
  cached_entries: 18000,
  est_reindex_cost_usd: 0.144,
};

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CacheEconomicsPanel instanceId="i1" />
    </QueryClientProvider>,
  );
}

describe("CacheEconomicsPanel", () => {
  it("shows estimates with the price basis", async () => {
    vi.mocked(client.getCacheEconomics).mockResolvedValue(econ);
    mount();
    expect(await screen.findByTestId("econ-saved")).toHaveTextContent("$0.04");
    expect(screen.getByTestId("econ-spend")).toHaveTextContent("$0.008");
    expect(screen.getByText(/text-embedding-3-small/)).toBeInTheDocument();
  });

  it("renders the local/unknown-price state without dollar figures", async () => {
    vi.mocked(client.getCacheEconomics).mockResolvedValue({
      ...econ,
      provider: "ollama",
      model: "nomic-embed-text",
      price_usd_per_mtok: null,
      est_spend_usd: null,
      est_saved_usd: null,
      est_reindex_cost_usd: null,
    });
    mount();
    expect(await screen.findByTestId("econ-no-price")).toBeInTheDocument();
  });
});
