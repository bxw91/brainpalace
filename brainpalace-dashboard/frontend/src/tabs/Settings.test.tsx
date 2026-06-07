import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Settings } from "./Settings";
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
  vi.mocked(client.getSettings).mockResolvedValue({
    host: "127.0.0.1",
    port: 8787,
    poll_s: 5,
    token_set: false,
    token: "",
    version: "26.6.25",
    runtime: { running: true, port: 8787, base_url: "http://127.0.0.1:8787/dashboard/" },
  });
});

describe("Settings tab (control-plane)", () => {
  it("edits port and saves after confirmation", async () => {
    vi.mocked(client.patchSettings).mockResolvedValue({
      ok: true,
      restart_required: ["port"],
    });
    wrap(<Settings />);

    const portInput = (await screen.findByTestId("input-port")) as HTMLInputElement;
    expect(portInput.value).toBe("8787");
    fireEvent.change(portInput, { target: { value: "9001" } });

    fireEvent.click(screen.getByTestId("btn-save-settings"));
    // Mutation is confirm-gated.
    expect(client.patchSettings).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    await waitFor(() =>
      expect(client.patchSettings).toHaveBeenCalledWith(
        expect.objectContaining({ port: 9001 }),
      ),
    );
    expect(await screen.findByTestId("toast-success")).toBeInTheDocument();
  });

  it("shows a field error from a 422", async () => {
    vi.mocked(client.patchSettings).mockRejectedValue({
      errors: [{ field: "port", message: "port must be 1–65535" }],
    });
    wrap(<Settings />);
    fireEvent.change(await screen.findByTestId("input-port"), {
      target: { value: "70000" },
    });
    fireEvent.click(screen.getByTestId("btn-save-settings"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));
    expect(await screen.findByTestId("field-error-port")).toHaveTextContent(
      "port must be 1–65535",
    );
  });
});
