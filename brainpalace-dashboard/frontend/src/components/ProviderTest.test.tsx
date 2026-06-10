import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ProviderTest } from "./ProviderTest";
import { ToastProvider } from "./Toast";
import * as client from "../api/client";

vi.mock("../api/client");

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <ProviderTest instanceId="i1" />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("ProviderTest", () => {
  it("runs the test and shows ok + failure chips", async () => {
    vi.mocked(client.testProviders).mockResolvedValue({
      embedding: {
        provider: "openai",
        model: "text-embedding-3-small",
        ok: true,
        latency_ms: 212.4,
        error: null,
      },
      summarization: {
        provider: "anthropic",
        model: "claude-haiku-4-5-20251001",
        ok: true,
        checked: "config-only",
        error: null,
      },
    });
    mount();
    fireEvent.click(screen.getByTestId("btn-test-providers"));
    expect(await screen.findByTestId("provider-chip-embedding")).toHaveTextContent(
      "ok",
    );
    expect(screen.getByText(/212 ms/)).toBeInTheDocument();
  });
});
