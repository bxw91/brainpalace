import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Ingest } from "./Ingest";
import { ToastProvider } from "../components/Toast";
import * as client from "../api/client";
import type { IngestSourceRow } from "../api/types";

vi.mock("../api/client");

const sources: IngestSourceRow[] = [
  {
    source_id: "email-2024",
    domain: "home",
    source: "scanner",
    chunk_count: 4,
    ingested_at: "2026-07-20T10:00:00Z",
  },
  {
    source_id: "notes-alpha",
    domain: "work",
    source: "manual",
    chunk_count: 2,
    ingested_at: "2026-07-21T11:00:00Z",
  },
];

const chunks = {
  source_id: "email-2024",
  total: 2,
  offset: 0,
  limit: 100,
  chunks: [
    { chunk_id: "ic1", text: "hello world", metadata: { domain: "home" } },
    { chunk_id: "ic2", text: "second chunk", metadata: { domain: "home" } },
  ],
};

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <Ingest instanceId="i1" />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("Ingest tab", () => {
  beforeEach(() => {
    vi.mocked(client.getIngestSources).mockResolvedValue({
      sources,
      total: sources.length,
    });
    vi.mocked(client.getIngestChunks).mockResolvedValue(chunks);
  });

  it("lists ingested sources with chunk counts", async () => {
    mount();
    expect(await screen.findByText("email-2024")).toBeInTheDocument();
    expect(screen.getByText("notes-alpha")).toBeInTheDocument();
    expect(screen.getByTestId("ingest-count")).toHaveTextContent("2 sources");
  });

  it("opens the chunk drawer on row click", async () => {
    mount();
    fireEvent.click(await screen.findByText("email-2024"));
    expect(await screen.findByTestId("ingest-chunk-drawer")).toBeInTheDocument();
    expect(await screen.findByTestId("ingest-chunk-ic1")).toBeInTheDocument();
    await waitFor(() =>
      expect(client.getIngestChunks).toHaveBeenCalledWith(
        "i1",
        expect.objectContaining({ source_id: "email-2024" }),
      ),
    );
  });

  it("filters the sources list client-side", async () => {
    mount();
    await screen.findByText("email-2024");
    fireEvent.change(screen.getByTestId("input-ingest-contains"), {
      target: { value: "work" },
    });
    await waitFor(() =>
      expect(screen.queryByText("email-2024")).not.toBeInTheDocument(),
    );
    expect(screen.getByText("notes-alpha")).toBeInTheDocument();
    expect(screen.getByTestId("ingest-count")).toHaveTextContent("1 source (filtered)");
  });

  it("shows an empty state when nothing is ingested", async () => {
    vi.mocked(client.getIngestSources).mockResolvedValue({ sources: [], total: 0 });
    mount();
    expect(await screen.findByText(/No ingested sources/)).toBeInTheDocument();
  });
});
