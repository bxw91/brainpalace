import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Sessions } from "./Sessions";
import { ToastProvider } from "../components/Toast";
import * as client from "../api/client";
import type { MemoriesPayload } from "../api/types";

vi.mock("../api/client");

const status = {
  session_chunks: 12,
  features: {
    session_archive: {
      enabled: true,
      retain_days: 0,
      archived_sessions: 38,
      archived_files: 167,
      archived_bytes: 99767000,
      tombstoned: 0,
    },
    session_memory: {
      enabled: true,
      watcher_running: true,
      session_chunks: 12,
      curated_memories: 2,
      archived_sessions: 38,
    },
  },
};

const memories: MemoriesPayload = {
  total: 2,
  char_count: 120,
  char_cap: 8000,
  memories: [
    { id: "m1", content: "Prefer poetry over pip.", category: "preference" },
    { id: "m2", content: "Server binds 8000-8100.", category: "fact" },
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
  vi.mocked(client.getInstanceStatus).mockResolvedValue(status as never);
  vi.mocked(client.getMemories).mockResolvedValue(memories);
  vi.mocked(client.memoryObsolete).mockResolvedValue({ ok: true });
  vi.mocked(client.memoryDelete).mockResolvedValue({ ok: true });
  vi.mocked(client.memoryRebuild).mockResolvedValue({ ok: true });
  vi.mocked(client.sessionsReindex).mockResolvedValue({ ok: true });
  vi.mocked(client.getSessionArchive).mockResolvedValue({
    sessions: [],
    archived_sessions: 0,
    archived_files: 0,
    tombstoned: 0,
    archived_bytes: 0,
  });
  vi.mocked(client.getDecisions).mockResolvedValue({ decisions: [] });
  vi.mocked(client.getDecisionTimeline).mockResolvedValue({
    entity: "",
    timeline: [],
  });
  vi.mocked(client.memoryCreate).mockResolvedValue({ ok: true });
});

describe("Sessions tab", () => {
  it("shows archive on/off and counts", async () => {
    wrap(<Sessions instanceId="a" />);
    const archive = await screen.findByTestId("card-session-archive");
    expect(within(archive).getByText("on")).toBeInTheDocument();
    expect(within(archive).getByText(/167/)).toBeInTheDocument();
  });

  it("shows the session index card with chunk + memory counts", async () => {
    wrap(<Sessions instanceId="a" />);
    const idx = await screen.findByTestId("card-session-index");
    expect(within(idx).getByText(/12/)).toBeInTheDocument();
  });

  it("renders curated memory rows", async () => {
    wrap(<Sessions instanceId="a" />);
    expect(await screen.findByText("Prefer poetry over pip.")).toBeInTheDocument();
  });

  it("Obsolete on a memory calls memoryObsolete", async () => {
    wrap(<Sessions instanceId="a" />);
    await screen.findByText("Prefer poetry over pip.");
    fireEvent.click(
      within(screen.getByTestId("memory-row-m1")).getByTestId("btn-obsolete-m1"),
    );
    fireEvent.click(await screen.findByTestId("btn-confirm"));
    await waitFor(() => expect(client.memoryObsolete).toHaveBeenCalledWith("a", "m1"));
  });

  it("Delete on a memory is confirm-gated then calls memoryDelete", async () => {
    wrap(<Sessions instanceId="a" />);
    await screen.findByText("Prefer poetry over pip.");
    fireEvent.click(
      within(screen.getByTestId("memory-row-m1")).getByTestId("btn-delete-m1"),
    );
    const dialog = await screen.findByTestId("confirm-dialog");
    fireEvent.click(within(dialog).getByTestId("btn-confirm"));
    await waitFor(() => expect(client.memoryDelete).toHaveBeenCalledWith("a", "m1"));
  });

  it("Rebuild shadow index calls memoryRebuild", async () => {
    wrap(<Sessions instanceId="a" />);
    await screen.findByText("Prefer poetry over pip.");
    fireEvent.click(screen.getByTestId("btn-rebuild-memories"));
    const dialog = await screen.findByTestId("confirm-dialog");
    fireEvent.click(within(dialog).getByTestId("btn-confirm"));
    await waitFor(() => expect(client.memoryRebuild).toHaveBeenCalledWith("a"));
  });

  it("Re-index transcripts calls sessionsReindex", async () => {
    wrap(<Sessions instanceId="a" />);
    await screen.findByText("Prefer poetry over pip.");
    fireEvent.click(screen.getByTestId("btn-sessions-reindex"));
    const dialog = await screen.findByTestId("confirm-dialog");
    fireEvent.click(within(dialog).getByTestId("btn-confirm"));
    await waitFor(() => expect(client.sessionsReindex).toHaveBeenCalledWith("a"));
  });

  it("shows stopped state when unreachable", async () => {
    vi.mocked(client.getInstanceStatus).mockRejectedValue(
      new client.InstanceUnreachableError("down", 502),
    );
    vi.mocked(client.getMemories).mockRejectedValue(
      new client.InstanceUnreachableError("down", 502),
    );
    wrap(<Sessions instanceId="a" />);
    expect(await screen.findByTestId("sessions-stopped")).toBeInTheDocument();
  });

  it("shows an error state with retry on a non-unreachable failure", async () => {
    vi.mocked(client.getInstanceStatus).mockRejectedValue(new Error("sess 500"));
    vi.mocked(client.getMemories).mockResolvedValue(memories);
    wrap(<Sessions instanceId="a" />);
    const err = await screen.findByTestId("sessions-error");
    expect(within(err).getByText(/sess 500/)).toBeInTheDocument();
    expect(screen.getByTestId("sessions-error-retry")).toBeInTheDocument();
  });

  it("mounts the composer, decision timeline, and archive panels", async () => {
    wrap(<Sessions instanceId="a" />);
    expect(await screen.findByTestId("memory-composer")).toBeInTheDocument();
    expect(await screen.findByTestId("decision-timeline")).toBeInTheDocument();
    // archive panel renders once the (zeroed) archive payload resolves
    expect(await screen.findByTestId("session-archive")).toBeInTheDocument();
  });

  it("shows the empty state when there are no curated memories", async () => {
    vi.mocked(client.getMemories).mockResolvedValue({
      total: 0,
      char_count: 0,
      char_cap: 8000,
      memories: [],
    });
    wrap(<Sessions instanceId="a" />);
    expect(
      await screen.findByText(/no curated memories yet/i),
    ).toBeInTheDocument();
  });
});
