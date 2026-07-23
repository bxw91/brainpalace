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
      features: { git_index: { enabled: true, commit_count: 42 } },
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

  it("renders rows and alerts from the server report", async () => {
    vi.mocked(client.getInstanceStatus).mockResolvedValue({
      total_documents: 1,
      total_chunks: 1,
      indexed_folders: ["/a"],
      report: {
        rows: [
          {
            key: "session_queue",
            label: "Session Queue",
            value: "330 pending",
            tone: "warn",
          },
          {
            key: "read_only",
            label: "Read-Only",
            value: "ON — provider calls disabled",
            tone: "bad",
          },
        ],
        alerts: [
          {
            kind: "index_drift",
            severity: "warn",
            title: "Index drift",
            lines: ["embedding model changed"],
          },
        ],
      },
    } as never);

    wrap(<Status instanceId="inst-1" />);

    expect(await screen.findByText("Session Queue")).toBeInTheDocument();
    expect(screen.getByText("330 pending")).toBeInTheDocument();
    expect(screen.getByText("Index drift")).toBeInTheDocument(); // alert → banner
    expect(screen.getByText("embedding model changed")).toBeInTheDocument();
    // read_only → banner (BANNER_KEYS), not a plain row
    expect(screen.getByText("ON — provider calls disabled")).toBeInTheDocument();
  });

  it("promotes read_only/self_heal/index_health rows to banners, keeps other rows in the list", async () => {
    vi.mocked(client.getInstanceStatus).mockResolvedValue({
      total_documents: 1,
      total_chunks: 1,
      indexed_folders: ["/a"],
      report: {
        rows: [
          {
            key: "self_heal",
            label: "Self-Heal",
            value:
              "recovered 4878/4878 chunk(s) from cache+dead (no re-embed); stage 2 skipped — read-only (no deletes)",
            tone: "good",
          },
          {
            key: "index_health",
            label: "Index Health",
            value: "⚠ 2 heal event(s), ~40 vectors shed",
            tone: "warn",
          },
          {
            key: "bm25_language",
            label: "BM25 Language",
            value: "en (engine: stem)",
            tone: "default",
          },
        ],
        alerts: [],
      },
    } as never);

    wrap(<Status instanceId="inst-1" />);

    expect(await screen.findByText("Self-Heal")).toBeInTheDocument();
    expect(screen.getByText(/stage 2 skipped/)).toBeInTheDocument();
    expect(screen.getByText("Index Health")).toBeInTheDocument();
    // A non-banner row still renders in the generic server-status list.
    expect(screen.getByText("BM25 Language")).toBeInTheDocument();
    expect(screen.getByText("en (engine: stem)")).toBeInTheDocument();
  });

  it("does NOT show any alert banner when the report has none", async () => {
    vi.mocked(client.getInstanceStatus).mockResolvedValue({
      total_documents: 5,
      total_chunks: 50,
      indexed_folders: ["/a"],
      report: { rows: [], alerts: [] },
    } as never);
    wrap(<Status instanceId="inst-1" />);
    await screen.findByTestId("stat-documents");
    expect(screen.queryByText("Index drift")).toBeNull();
    expect(screen.queryByText("Indexing paused")).toBeNull();
  });

  it("shows the stopped state when the instance is unreachable", async () => {
    const err = new client.InstanceUnreachableError("instance unreachable", 502);
    vi.mocked(client.getInstanceStatus).mockRejectedValue(err);
    wrap(<Status instanceId="inst-1" />);
    expect(await screen.findByTestId("status-stopped")).toBeInTheDocument();
  });
});
