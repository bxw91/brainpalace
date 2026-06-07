import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Instances } from "./Instances";
import { ToastProvider } from "../components/Toast";
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
  inst({
    id: "a",
    name: "alpha",
    status: "running",
    base_url: "http://127.0.0.1:9001",
    pid: 111,
  }),
  inst({
    id: "b",
    name: "beta",
    status: "running",
    base_url: "http://127.0.0.1:9002",
    pid: 222,
  }),
  inst({ id: "c", name: "gamma", status: "stopped" }),
];

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
  vi.mocked(client.listInstances).mockResolvedValue(rows);
  vi.mocked(client.stopInstance).mockResolvedValue({ ok: true });
  vi.mocked(client.startInstance).mockResolvedValue({ ok: true });
  vi.mocked(client.restartInstance).mockResolvedValue({ ok: true });
  vi.mocked(client.forgetInstance).mockResolvedValue({ ok: true });
  vi.mocked(client.registerProject).mockResolvedValue({ ok: true });
});

describe("Instances tab", () => {
  it("shows name / status / port / pid", async () => {
    wrap(<Instances />);
    expect(await screen.findByText("alpha")).toBeInTheDocument();
    const row = screen.getByTestId("row-a");
    expect(within(row).getByText(/9001/)).toBeInTheDocument(); // port
    expect(within(row).getByText("111")).toBeInTheDocument(); // pid
    expect(within(row).getByTestId("status-a")).toHaveAttribute(
      "data-status",
      "running",
    );
  });

  it("Stop -> ConfirmDialog -> stopInstance(id)", async () => {
    wrap(<Instances />);
    await screen.findByText("alpha");
    fireEvent.click(within(screen.getByTestId("row-a")).getByTestId("btn-stop-a"));
    // confirm dialog appears
    const dialog = await screen.findByTestId("confirm-dialog");
    fireEvent.click(within(dialog).getByTestId("btn-confirm"));
    await waitFor(() => expect(client.stopInstance).toHaveBeenCalledWith("a"));
  });

  it("Start on a stopped row calls startInstance(id)", async () => {
    wrap(<Instances />);
    await screen.findByText("gamma");
    fireEvent.click(within(screen.getByTestId("row-c")).getByTestId("btn-start-c"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));
    await waitFor(() => expect(client.startInstance).toHaveBeenCalledWith("c"));
  });

  it("bulk-select two running rows + Stop selected stops both", async () => {
    wrap(<Instances />);
    await screen.findByText("alpha");
    fireEvent.click(screen.getByTestId("select-a"));
    fireEvent.click(screen.getByTestId("select-b"));
    fireEvent.click(screen.getByTestId("btn-bulk-stop"));
    const dialog = await screen.findByTestId("confirm-dialog");
    fireEvent.click(within(dialog).getByTestId("btn-confirm"));
    await waitFor(() => {
      expect(client.stopInstance).toHaveBeenCalledWith("a");
      expect(client.stopInstance).toHaveBeenCalledWith("b");
    });
  });

  it("Remove from list (forget) on a stopped row, with confirm", async () => {
    wrap(<Instances />);
    await screen.findByText("gamma");
    fireEvent.click(within(screen.getByTestId("row-c")).getByTestId("btn-forget-c"));
    const dialog = await screen.findByTestId("confirm-dialog");
    fireEvent.click(within(dialog).getByTestId("btn-confirm"));
    await waitFor(() => expect(client.forgetInstance).toHaveBeenCalledWith("c"));
  });

  it("Register project posts the entered path", async () => {
    wrap(<Instances />);
    await screen.findByText("alpha");
    fireEvent.click(screen.getByTestId("btn-register-open"));
    const dialog = await screen.findByTestId("register-dialog");
    fireEvent.change(within(dialog).getByTestId("input-register-path"), {
      target: { value: "/srv/new-project" },
    });
    fireEvent.click(within(dialog).getByTestId("btn-register-submit"));
    await waitFor(() =>
      expect(client.registerProject).toHaveBeenCalledWith("/srv/new-project"),
    );
  });

  it("shows an error state with retry when the fleet list fails", async () => {
    vi.mocked(client.listInstances).mockRejectedValue(new Error("fleet 500"));
    wrap(<Instances />);
    const err = await screen.findByTestId("instances-error");
    expect(within(err).getByText(/fleet 500/)).toBeInTheDocument();
    expect(screen.getByTestId("instances-error-retry")).toBeInTheDocument();
  });

  it("shows the empty table message when no instances are registered", async () => {
    vi.mocked(client.listInstances).mockResolvedValue([]);
    wrap(<Instances />);
    expect(
      await screen.findByText(/no instances registered/i),
    ).toBeInTheDocument();
  });
});
