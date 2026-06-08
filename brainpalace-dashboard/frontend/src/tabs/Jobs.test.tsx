import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Jobs } from "./Jobs";
import { ToastProvider } from "../components/Toast";
import * as client from "../api/client";
import type { JobsPayload } from "../api/types";

vi.mock("../api/client");

const jobs: JobsPayload = {
  jobs: [
    {
      id: "job_run",
      status: "running",
      folder_path: "/repo/alpha",
      operation: "index",
      include_code: true,
      source: "manual",
      enqueued_at: "2026-06-06T20:00:00Z",
      started_at: "2026-06-06T20:00:01Z",
      finished_at: null,
      progress_percent: 55,
      chunks_added: 0,
      chunks_removed: 0,
      error: null,
    },
    {
      id: "job_done",
      status: "done",
      folder_path: "/repo/beta",
      operation: "index",
      include_code: true,
      source: "auto",
      enqueued_at: "2026-06-06T19:00:00Z",
      started_at: "2026-06-06T19:00:01Z",
      finished_at: "2026-06-06T19:05:00Z",
      progress_percent: 100,
      chunks_added: 120,
      chunks_removed: 30,
      error: null,
    },
  ],
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
  vi.mocked(client.getJobs).mockResolvedValue(jobs);
  vi.mocked(client.cancelJob).mockResolvedValue({ ok: true });
});

describe("Jobs tab", () => {
  it("renders job rows with id, status, progress", async () => {
    wrap(<Jobs instanceId="a" />);
    expect(await screen.findByText("job_run")).toBeInTheDocument();
    const row = screen.getByTestId("job-row-job_run");
    expect(within(row).getByText(/running/i)).toBeInTheDocument();
    expect(within(row).getByText(/55/)).toBeInTheDocument();
  });

  it("shows chunk add/remove deltas and a computed duration", async () => {
    wrap(<Jobs instanceId="a" />);
    await screen.findByText("job_done");
    const row = screen.getByTestId("job-row-job_done");
    expect(within(row).getByText("+120")).toBeInTheDocument();
    expect(within(row).getByText("−30")).toBeInTheDocument();
    // 19:00:01 → 19:05:00 ≈ 4m 59s
    expect(within(row).getByText(/4m 59s/)).toBeInTheDocument();
  });

  it("Cancel on a running job is confirm-gated then calls cancelJob", async () => {
    wrap(<Jobs instanceId="a" />);
    await screen.findByText("job_run");
    fireEvent.click(
      within(screen.getByTestId("job-row-job_run")).getByTestId("btn-cancel-job_run"),
    );
    const dialog = await screen.findByTestId("confirm-dialog");
    fireEvent.click(within(dialog).getByTestId("btn-confirm"));
    await waitFor(() => expect(client.cancelJob).toHaveBeenCalledWith("a", "job_run"));
  });

  it("does not offer Cancel on a finished job", async () => {
    wrap(<Jobs instanceId="a" />);
    await screen.findByText("job_done");
    const row = screen.getByTestId("job-row-job_done");
    expect(within(row).queryByTestId("btn-cancel-job_done")).toBeNull();
  });

  it("shows the stopped state when unreachable", async () => {
    vi.mocked(client.getJobs).mockRejectedValue(
      new client.InstanceUnreachableError("down", 502),
    );
    wrap(<Jobs instanceId="a" />);
    expect(await screen.findByTestId("jobs-stopped")).toBeInTheDocument();
  });

  it("shows an error state with retry on a non-unreachable failure", async () => {
    vi.mocked(client.getJobs).mockRejectedValue(new Error("jobs 500"));
    wrap(<Jobs instanceId="a" />);
    const err = await screen.findByTestId("jobs-error");
    expect(within(err).getByText(/jobs 500/)).toBeInTheDocument();
    expect(screen.getByTestId("jobs-error-retry")).toBeInTheDocument();
  });

  it("shows the empty state when there are no jobs", async () => {
    vi.mocked(client.getJobs).mockResolvedValue({ jobs: [] });
    wrap(<Jobs instanceId="a" />);
    expect(await screen.findByText(/no indexing jobs yet/i)).toBeInTheDocument();
  });
});
