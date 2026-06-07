import { render, screen, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Status } from "./Status";
import { ToastProvider } from "../components/Toast";
import * as client from "../api/client";

vi.mock("../api/client");

function wrap(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe("Status tab", () => {
  it("renders the selected instance's bp-status stats", async () => {
    vi.mocked(client.getInstanceStatus).mockResolvedValue({
      total_documents: 120,
      code_documents: 100,
      doc_documents: 20,
      total_chunks: 4967,
      total_code_chunks: 4000,
      total_doc_chunks: 967,
      // The server returns a LIST of folder paths, not a count (regression guard).
      indexed_folders: ["/a", "/b"],
      supported_languages: ["python", "typescript"],
      git_commits: 42,
      graph_index: {
        enabled: true,
        entity_count: 7,
        relationship_count: 9,
        store_type: "sqlite",
      },
      embedding_cache: { hit_rate: 0.9 },
      file_watcher: { running: true },
    } as never);

    wrap(<Status instanceId="inst-1" />);

    // Wait for the data branch (the skeleton shares the tab-status testid, so we
    // wait on a stat card to know the status query resolved).
    expect(
      within(await screen.findByTestId("stat-documents")).getByText("120"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("stat-chunks")).getByText("4,967"),
    ).toBeInTheDocument();
    // Folder COUNT derived from the array length (the bug we fixed).
    expect(
      within(screen.getByTestId("stat-folders")).getByText("2"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("stat-git")).getByText("42"),
    ).toBeInTheDocument();
  });

  it("shows the stopped state when the instance is unreachable", async () => {
    const err = new client.InstanceUnreachableError("instance unreachable", 502);
    vi.mocked(client.getInstanceStatus).mockRejectedValue(err);
    wrap(<Status instanceId="inst-1" />);
    expect(await screen.findByTestId("status-stopped")).toBeInTheDocument();
  });
});
