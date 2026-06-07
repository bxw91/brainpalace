import { render, screen, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Overview } from "./Overview";
import * as client from "../api/client";
import type { Instance } from "../api/types";

vi.mock("../api/client");

function inst(over: Partial<Instance>): Instance {
  return {
    id: "x",
    name: "x",
    project_root: "/p/x",
    state_dir: "",
    base_url: "",
    pid: null,
    mode: "project",
    status: "stopped",
    started_at: "",
    ...over,
  };
}

const rows: Instance[] = [
  inst({ id: "a", name: "alpha", status: "running", base_url: "http://x" }),
  inst({ id: "b", name: "beta", status: "running", base_url: "http://y" }),
  inst({ id: "c", name: "gamma", status: "stopped" }),
  inst({ id: "d", name: "delta", status: "unhealthy", base_url: "http://z" }),
];

function wrap(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(client.listInstances).mockResolvedValue(rows);
  vi.mocked(client.getInstanceStatus).mockImplementation(async (id: string) => {
    if (id === "a") return { total_chunks: 100, total_documents: 10 } as never;
    if (id === "b") return { total_chunks: 200, total_documents: 20 } as never;
    if (id === "d") return { total_chunks: 50, total_documents: 5 } as never;
    throw new client.InstanceUnreachableError("down");
  });
});

describe("Overview tab", () => {
  it("shows running / stopped counts in stat cards", async () => {
    wrap(<Overview />);
    const running = await screen.findByTestId("stat-running");
    await within(running).findByText("2");
    const stopped = screen.getByTestId("stat-stopped");
    expect(within(stopped).getByText("1")).toBeInTheDocument();
    const unhealthy = screen.getByTestId("stat-unhealthy");
    expect(within(unhealthy).getByText("1")).toBeInTheDocument();
  });

  it("aggregates total chunks across reachable instances", async () => {
    wrap(<Overview />);
    const card = await screen.findByTestId("stat-chunks");
    // 100 + 200 + 50 = 350
    await within(card).findByText("350");
  });

  it("renders an alert row for an unhealthy instance", async () => {
    wrap(<Overview />);
    const alerts = await screen.findByTestId("alerts");
    expect(within(alerts).getByText(/delta/)).toBeInTheDocument();
  });

  it("shows the no-instances empty state when the fleet is empty", async () => {
    vi.mocked(client.listInstances).mockResolvedValue([]);
    wrap(<Overview />);
    const empty = await screen.findByTestId("overview-empty");
    expect(within(empty).getByText(/no instances yet/i)).toBeInTheDocument();
    expect(within(empty).getByText(/brainpalace start/i)).toBeInTheDocument();
  });

  it("shows an error state with retry when the fleet list fails", async () => {
    vi.mocked(client.listInstances).mockRejectedValue(new Error("fleet down"));
    wrap(<Overview />);
    const err = await screen.findByTestId("overview-error");
    expect(within(err).getByText(/fleet down/)).toBeInTheDocument();
    expect(screen.getByTestId("overview-error-retry")).toBeInTheDocument();
  });
});
