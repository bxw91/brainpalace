import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { InstanceActions } from "./InstanceActions";
import { ToastProvider } from "./Toast";
import * as client from "../api/client";
import type { Instance } from "../api/types";

vi.mock("../api/client");

function inst(over: Partial<Instance>): Instance {
  return {
    id: "a",
    name: "alpha",
    project_root: "/p/a",
    state_dir: "",
    base_url: "http://127.0.0.1:9001",
    pid: 111,
    mode: "project",
    status: "running",
    started_at: "",
    ...over,
  };
}

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
  vi.mocked(client.startInstance).mockResolvedValue({ ok: true });
  vi.mocked(client.stopInstance).mockResolvedValue({ ok: true });
  vi.mocked(client.restartInstance).mockResolvedValue({ ok: true });
});

describe("InstanceActions", () => {
  it("running: shows Stop + Restart, not Start", () => {
    wrap(<InstanceActions instance={inst({ status: "running" })} />);
    expect(screen.getByTestId("btn-detail-stop")).toBeInTheDocument();
    expect(screen.getByTestId("btn-detail-restart")).toBeInTheDocument();
    expect(screen.queryByTestId("btn-detail-start")).not.toBeInTheDocument();
  });

  it("stopped: shows Start, not Stop/Restart", () => {
    wrap(<InstanceActions instance={inst({ status: "stopped", base_url: "" })} />);
    expect(screen.getByTestId("btn-detail-start")).toBeInTheDocument();
    expect(screen.queryByTestId("btn-detail-stop")).not.toBeInTheDocument();
    expect(screen.queryByTestId("btn-detail-restart")).not.toBeInTheDocument();
  });

  it("Stop calls stopInstance after confirm", async () => {
    wrap(<InstanceActions instance={inst({ status: "running" })} />);
    fireEvent.click(screen.getByTestId("btn-detail-stop"));
    fireEvent.click(screen.getByTestId("btn-confirm"));
    await waitFor(() => expect(client.stopInstance).toHaveBeenCalledWith("a"));
  });

  it("Start calls startInstance after confirm", async () => {
    wrap(<InstanceActions instance={inst({ status: "stopped", base_url: "" })} />);
    fireEvent.click(screen.getByTestId("btn-detail-start"));
    fireEvent.click(screen.getByTestId("btn-confirm"));
    await waitFor(() => expect(client.startInstance).toHaveBeenCalledWith("a"));
  });
});
