import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { JobDrawer } from "./JobDrawer";
import * as client from "../api/client";
import type { JobDetail } from "../api/types";

vi.mock("../api/client");

function baseDetail(eviction: JobDetail["eviction_summary"]): JobDetail {
  return {
    id: "job_x",
    status: "done",
    folder_path: "/repo",
    operation: "index",
    include_code: true,
    source: "watch",
    enqueued_at: "2026-06-06T19:00:00Z",
    started_at: "2026-06-06T19:00:01Z",
    finished_at: "2026-06-06T19:00:05Z",
    execution_time_ms: 4000,
    progress: null,
    progress_percent: 100,
    total_documents: 1,
    total_chunks: 8136,
    chunks_added: 1,
    chunks_removed: 0,
    error: null,
    retry_count: 0,
    cancel_requested: false,
    eviction_summary: eviction,
  };
}

function wrap(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("JobDrawer file lists", () => {
  it("lists every file inline when a list has fewer than 20 entries", async () => {
    const files = [
      "/repo/brainpalace-cli/tests/commands/test_verify_docs_skip_fresh.py",
      "/repo/docs/a-really-long-path/that-should-not-be-truncated.md",
    ];
    vi.mocked(client.getJobDetail).mockResolvedValue(
      baseDetail({ files_added: 0, files_changed: files, files_deleted: 0 }),
    );
    wrap(<JobDrawer instanceId="a" jobId="job_x" onClose={() => {}} />);

    const list = await screen.findByTestId("file-list-items-files_changed");
    // Both full paths rendered, untruncated.
    for (const f of files) {
      expect(within(list).getByText(f)).toBeInTheDocument();
    }
    // No "show all" button when under the threshold.
    expect(
      screen.queryByTestId("btn-show-all-files_changed"),
    ).not.toBeInTheDocument();
  });

  it("collapses a list of 20+ behind a Show all button that reveals all", async () => {
    const files = Array.from({ length: 25 }, (_, i) => `/repo/pkg/file_${i}.py`);
    vi.mocked(client.getJobDetail).mockResolvedValue(
      baseDetail({ files_changed: files }),
    );
    wrap(<JobDrawer instanceId="a" jobId="job_x" onClose={() => {}} />);

    const btn = await screen.findByTestId("btn-show-all-files_changed");
    expect(btn).toHaveTextContent("Show all 25 files");
    // List hidden until expanded.
    expect(
      screen.queryByTestId("file-list-items-files_changed"),
    ).not.toBeInTheDocument();

    fireEvent.click(btn);

    const list = screen.getByTestId("file-list-items-files_changed");
    expect(within(list).getByText("/repo/pkg/file_0.py")).toBeInTheDocument();
    expect(within(list).getByText("/repo/pkg/file_24.py")).toBeInTheDocument();
    // Button gone after expanding.
    expect(
      screen.queryByTestId("btn-show-all-files_changed"),
    ).not.toBeInTheDocument();
  });
});
