import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Runtime } from "./Runtime";
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
  vi.mocked(client.getRuntimeConfig).mockResolvedValue({
    bind_host: "127.0.0.1",
    port_range_start: 8000,
    port_range_end: 8100,
    auto_port: true,
  });
});

describe("Runtime tab (config.json bind)", () => {
  it("loads the bind and saves edits via patchRuntimeConfig", async () => {
    vi.mocked(client.patchRuntimeConfig).mockResolvedValue({
      ok: true,
      restarted: false,
      restart_required: true,
    });
    wrap(<Runtime instanceId="inst-1" />);

    const host = (await screen.findByTestId("input-bind_host")) as HTMLInputElement;
    expect(host.value).toBe("127.0.0.1");
    fireEvent.change(host, { target: { value: "0.0.0.0" } });

    fireEvent.click(screen.getByTestId("btn-save-runtime"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    await waitFor(() =>
      expect(client.patchRuntimeConfig).toHaveBeenCalledWith(
        "inst-1",
        expect.objectContaining({ bind_host: "0.0.0.0" }),
        false,
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
    wrap(<Runtime instanceId="inst-1" />);

    await screen.findByTestId("input-bind_host");
    fireEvent.click(screen.getByTestId("btn-save-runtime-restart"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    await waitFor(() =>
      expect(client.patchRuntimeConfig).toHaveBeenCalledWith(
        "inst-1",
        expect.anything(),
        true,
      ),
    );
  });

  it("shows a 422 field error from validation", async () => {
    vi.mocked(client.patchRuntimeConfig).mockRejectedValue({
      errors: [{ field: "port_range_start", message: "Port must be an integer 1–65535." }],
    });
    wrap(<Runtime instanceId="inst-1" />);

    const start = (await screen.findByTestId(
      "input-port_range_start",
    )) as HTMLInputElement;
    fireEvent.change(start, { target: { value: "70000" } });
    fireEvent.click(screen.getByTestId("btn-save-runtime"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    expect(
      await screen.findByTestId("field-error-port_range_start"),
    ).toHaveTextContent("Port must be an integer 1–65535.");
  });
});
