import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Folders } from "./Folders";
import { ToastProvider } from "../components/Toast";
import * as client from "../api/client";
import type { FoldersPayload, JobsPayload } from "../api/types";

vi.mock("../api/client");

const folders: FoldersPayload = {
  total: 2,
  folders: [
    {
      folder_path: "/repo/alpha",
      chunk_count: 5041,
      last_indexed: "2026-06-06T20:27:19.111760+00:00",
      watch_mode: "auto",
      watch_debounce_seconds: null,
    },
    {
      folder_path: "/repo/beta",
      chunk_count: 12,
      last_indexed: null,
      watch_mode: "off",
      watch_debounce_seconds: null,
    },
  ],
};

const idleJobs: JobsPayload = { jobs: [] };

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
  vi.mocked(client.getFolders).mockResolvedValue(folders);
  vi.mocked(client.getJobs).mockResolvedValue(idleJobs);
  vi.mocked(client.removeFolder).mockResolvedValue({ ok: true });
  vi.mocked(client.addFolder).mockResolvedValue({ ok: true });
  vi.mocked(client.resetIndex).mockResolvedValue({ ok: true });
});

describe("Folders tab", () => {
  it("renders folder rows with path, chunks and watch", async () => {
    wrap(<Folders instanceId="a" />);
    expect(await screen.findByText("/repo/alpha")).toBeInTheDocument();
    expect(screen.getByText("/repo/beta")).toBeInTheDocument();
    const row = screen.getByTestId("folder-row-/repo/alpha");
    expect(within(row).getByText(/5,041|5041/)).toBeInTheDocument();
    expect(within(row).getByText(/auto/i)).toBeInTheDocument();
  });

  it("Remove opens ConfirmDialog then calls removeFolder", async () => {
    wrap(<Folders instanceId="a" />);
    await screen.findByText("/repo/alpha");
    fireEvent.click(
      within(screen.getByTestId("folder-row-/repo/alpha")).getByTestId(
        "btn-remove-/repo/alpha",
      ),
    );
    const dialog = await screen.findByTestId("confirm-dialog");
    fireEvent.click(within(dialog).getByTestId("btn-confirm"));
    await waitFor(() =>
      expect(client.removeFolder).toHaveBeenCalledWith("a", "/repo/alpha"),
    );
  });

  it("Add folder opens picker and submits folder_path + types + watch", async () => {
    wrap(<Folders instanceId="a" />);
    await screen.findByText("/repo/alpha");
    fireEvent.click(screen.getByTestId("btn-add-folder"));
    const picker = await screen.findByTestId("folder-picker");
    fireEvent.change(within(picker).getByTestId("input-folder-path"), {
      target: { value: "/repo/gamma" },
    });
    fireEvent.change(within(picker).getByTestId("select-folder-type"), {
      target: { value: "docs" },
    });
    fireEvent.click(within(picker).getByTestId("btn-folder-add"));
    await waitFor(() =>
      expect(client.addFolder).toHaveBeenCalledWith("a", {
        folder_path: "/repo/gamma",
        include_types: ["docs"],
        watch_mode: "auto",
      }),
    );
  });

  it("Reset index is confirm-gated", async () => {
    wrap(<Folders instanceId="a" />);
    await screen.findByText("/repo/alpha");
    fireEvent.click(screen.getByTestId("btn-reset-index"));
    const dialog = await screen.findByTestId("confirm-dialog");
    fireEvent.click(within(dialog).getByTestId("btn-confirm"));
    await waitFor(() => expect(client.resetIndex).toHaveBeenCalledWith("a"));
  });

  it("shows JobProgress while a job is running", async () => {
    vi.mocked(client.getJobs).mockResolvedValue({
      jobs: [
        {
          id: "job_x",
          status: "running",
          folder_path: "/repo/alpha",
          operation: "index",
          include_code: true,
          source: "manual",
          enqueued_at: null,
          started_at: null,
          finished_at: null,
          progress_percent: 42,
          error: null,
        },
      ],
    });
    wrap(<Folders instanceId="a" />);
    const prog = await screen.findByTestId("job-progress");
    expect(within(prog).getByTestId("job-progress-pct")).toHaveTextContent("42%");
  });

  it("shows stopped state when the instance is unreachable", async () => {
    vi.mocked(client.getFolders).mockRejectedValue(
      new client.InstanceUnreachableError("down", 502),
    );
    vi.mocked(client.getJobs).mockRejectedValue(
      new client.InstanceUnreachableError("down", 502),
    );
    wrap(<Folders instanceId="a" />);
    expect(await screen.findByTestId("folders-stopped")).toBeInTheDocument();
  });

  it("shows an error state with retry on a non-unreachable failure", async () => {
    vi.mocked(client.getFolders).mockRejectedValue(new Error("boom 500"));
    wrap(<Folders instanceId="a" />);
    const err = await screen.findByTestId("folders-error");
    expect(within(err).getByText(/could not load/i)).toBeInTheDocument();
    expect(within(err).getByText(/boom 500/)).toBeInTheDocument();
    expect(screen.getByTestId("folders-error-retry")).toBeInTheDocument();
  });

  it("retry re-runs the folders query", async () => {
    vi.mocked(client.getFolders)
      .mockRejectedValueOnce(new Error("boom 500"))
      .mockResolvedValue(folders);
    wrap(<Folders instanceId="a" />);
    fireEvent.click(await screen.findByTestId("folders-error-retry"));
    expect(await screen.findByText("/repo/alpha")).toBeInTheDocument();
  });

  it("shows the empty state when no folders are indexed", async () => {
    vi.mocked(client.getFolders).mockResolvedValue({ total: 0, folders: [] });
    wrap(<Folders instanceId="a" />);
    expect(
      await screen.findByText(/no folders indexed yet/i),
    ).toBeInTheDocument();
  });
});
