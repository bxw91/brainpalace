import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { RuntimeSection } from "./Runtime";
import { ToastProvider } from "../components/Toast";
import * as client from "../api/client";

vi.mock("../api/client");

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
  vi.mocked(client.getRuntimeConfigEffective).mockResolvedValue({
    bind_host: { value: "127.0.0.1", source: "default", inherited: null },
    port_range_start: { value: 8000, source: "default", inherited: null },
    port_range_end: { value: 8100, source: "default", inherited: null },
    auto_port: { value: true, source: "default", inherited: null },
  });
});

describe("Runtime bind section (config.json, folded into Config)", () => {
  it("edits the host and saves an override via patchRuntimeConfig", async () => {
    vi.mocked(client.patchRuntimeConfig).mockResolvedValue({
      ok: true,
      restarted: false,
      restart_required: true,
    });
    wrap(<RuntimeSection instanceId="inst-1" />);

    // No global runtime value set → the inherit option falls back to the code
    // default (127.0.0.1), shown alongside the editable input.
    const host = (await screen.findByTestId("text-bind_host")) as HTMLInputElement;
    expect(screen.getByTestId("field-inherit-bind_host")).toHaveTextContent(
      /using code default: 127\.0\.0\.1/i,
    );
    fireEvent.change(host, { target: { value: "0.0.0.0" } });

    fireEvent.click(screen.getByTestId("btn-save-runtime"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    await waitFor(() =>
      expect(client.patchRuntimeConfig).toHaveBeenCalledWith(
        "inst-1",
        expect.objectContaining({ bind_host: "0.0.0.0" }),
        false,
        [],
      ),
    );
    expect(await screen.findByTestId("toast-success")).toBeInTheDocument();
  });

  it("Save + Restart passes restart=true", async () => {
    vi.mocked(client.patchRuntimeConfig).mockResolvedValue({
      ok: true,
      restarted: true,
      restart_required: false,
    });
    wrap(<RuntimeSection instanceId="inst-1" />);

    const host = (await screen.findByTestId("text-bind_host")) as HTMLInputElement;
    fireEvent.change(host, { target: { value: "0.0.0.0" } });
    fireEvent.click(screen.getByTestId("btn-save-restart-runtime"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    await waitFor(() =>
      expect(client.patchRuntimeConfig).toHaveBeenCalledWith(
        "inst-1",
        expect.anything(),
        true,
        [],
      ),
    );
  });

  it("shows a 422 field error from validation", async () => {
    vi.mocked(client.patchRuntimeConfig).mockRejectedValue({
      errors: [
        { field: "port_range_start", message: "Port must be an integer 1–65535." },
      ],
    });
    wrap(<RuntimeSection instanceId="inst-1" />);

    // Make a change so Save is enabled, then save into the rejecting mock.
    await screen.findByTestId("int-inc-port_range_start");
    fireEvent.click(screen.getByTestId("int-inc-port_range_start"));
    fireEvent.click(screen.getByTestId("btn-save-runtime"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    expect(
      await screen.findByTestId("field-error-port_range_start"),
    ).toHaveTextContent("Port must be an integer 1–65535.");
  });

  it("global scope edits the machine-wide bind via patchGlobalRuntimeConfig", async () => {
    vi.mocked(client.getGlobalRuntimeConfigEffective).mockResolvedValue({
      bind_host: { value: "127.0.0.1", source: "default", inherited: null },
      port_range_start: { value: 8000, source: "default", inherited: null },
      port_range_end: { value: 8100, source: "default", inherited: null },
      auto_port: { value: true, source: "default", inherited: null },
    });
    vi.mocked(client.patchGlobalRuntimeConfig).mockResolvedValue({
      ok: true,
      restart_required: true,
    });
    wrap(<RuntimeSection scope="global" />);

    const host = (await screen.findByTestId("text-bind_host")) as HTMLInputElement;
    fireEvent.change(host, { target: { value: "0.0.0.0" } });
    // Global layer has no single instance to restart.
    expect(screen.queryByTestId("btn-save-restart-runtime")).toBeNull();
    fireEvent.click(screen.getByTestId("btn-save-runtime"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    await waitFor(() =>
      expect(client.patchGlobalRuntimeConfig).toHaveBeenCalledWith(
        expect.objectContaining({ bind_host: "0.0.0.0" }),
        [],
      ),
    );
  });
});
