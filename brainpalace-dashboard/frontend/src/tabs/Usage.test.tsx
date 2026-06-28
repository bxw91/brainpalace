// frontend/src/tabs/Usage.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Usage } from "./Usage";
import { ToastProvider } from "../components/Toast";
import * as client from "../api/client";

vi.mock("../api/client");

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
}
beforeEach(() => vi.clearAllMocks());

describe("Usage tab", () => {
  it("renders separated token figures from /metrics/usage", async () => {
    vi.mocked(client.getUsageMetrics).mockResolvedValue({
      window: "24h", now_bucket: 29070720, bucket_size: 15,
      totals: [{ channel: "provider", provider: "anthropic", model: "h",
        source: "session", chunks: 0, calls: 36, triplets: 210,
        tokens_in: 88100, tokens_out: 12400, cache_read: 40300, cache_write: 1200, errors: 2 }],
      series: [{ bucket: 29070705, chunks: 0, calls: 1, triplets: 5,
        embed_tokens_in: 0, embed_cache_read: 0, llm_tokens_in: 80,
        llm_tokens_out: 12, llm_cache_read: 40, llm_cache_write: 5 }],
      series_by_source: [{ bucket: 29070705, channel: "provider", source: "session",
        tokens_in: 80, tokens_out: 12, cache_read: 40, cache_write: 5 }],
      queue: [{ source: "session", depth: 698, sampled_at: 1744243190 }],
    } as never);
    wrap(<Usage instanceId="inst-1" />);
    expect(await screen.findByTestId("usage-llm-tokens-in")).toHaveTextContent("88,100");
    expect(screen.getByTestId("usage-cache-read")).toHaveTextContent("40,300");
    expect(screen.getByTestId("usage-queue-session")).toHaveTextContent("698");
  });

  it("separates git backlog and flags rows whose feature is off", async () => {
    vi.mocked(client.getUsageMetrics).mockResolvedValue({
      window: "24h", now_bucket: 29070720, bucket_size: 15,
      totals: [], series: [], series_by_source: [],
      queue: [
        { source: "doc", depth: 300, sampled_at: 1744243190, active: false },
        { source: "git", depth: 12, sampled_at: 1744243190, active: false },
        { source: "session", depth: 167, sampled_at: 1744243190, active: true },
      ],
    } as never);
    wrap(<Usage instanceId="inst-1" />);
    // Git is its own row, distinct from documents.
    expect(await screen.findByTestId("usage-queue-doc")).toHaveTextContent("300");
    expect(screen.getByTestId("usage-queue-git")).toHaveTextContent("12");
    expect(screen.getByTestId("usage-queue-session")).toHaveTextContent("167");
    // Off rows carry a "not draining" note; the active one does not.
    expect(screen.getByTestId("usage-queue-doc-off")).toHaveTextContent(
      "extraction off — not draining",
    );
    expect(screen.getByTestId("usage-queue-git-off")).toHaveTextContent(
      "extraction off — not draining",
    );
    expect(screen.queryByTestId("usage-queue-session-off")).toBeNull();
  });

  it("shows the disabled state on 503", async () => {
    const err = new client.InstanceUnreachableError("disabled", 503);
    vi.mocked(client.getUsageMetrics).mockRejectedValue(err);
    wrap(<Usage instanceId="inst-1" />);
    expect(await screen.findByTestId("usage-disabled")).toBeInTheDocument();
  });

  it("shows the empty state when the window has no rows", async () => {
    vi.mocked(client.getUsageMetrics).mockResolvedValue({
      window: "24h", now_bucket: 29070720, bucket_size: 15, totals: [], series: [], series_by_source: [], queue: [],
    } as never);
    wrap(<Usage instanceId="inst-1" />);
    expect(await screen.findByTestId("usage-empty")).toBeInTheDocument();
  });
});
