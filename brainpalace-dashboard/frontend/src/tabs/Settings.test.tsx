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
    autostart: true,
    time_format: "24h",
    date_format: "dd.mm.yyyy",
    token_set: false,
    token: "",
    version: "26.6.25",
    runtime: { running: true, port: 8787, base_url: "http://127.0.0.1:8787/dashboard/" },
  });
  // Default: every field set in the file → controls render with a value.
  vi.mocked(client.getSettingsEffective).mockResolvedValue({
    host: { value: "127.0.0.1", source: "file" },
    port: { value: 8787, source: "file" },
    poll_s: { value: 5, source: "file" },
    token: { value: "", source: "file" },
    autostart: { value: true, source: "file" },
    time_format: { value: "24h", source: "file" },
    date_format: { value: "dd.mm.yyyy", source: "file" },
  });
});

const ALL_DEFAULT: client.SettingsEffective = {
  host: { value: "127.0.0.1", source: "default" },
  port: { value: 8787, source: "default" },
  poll_s: { value: 5, source: "default" },
  token: { value: "", source: "default" },
  autostart: { value: true, source: "default" },
  time_format: { value: "24h", source: "default" },
  date_format: { value: "dd.mm.yyyy", source: "default" },
};

describe("Settings tab (control-plane)", () => {
  it("edits port and saves after confirmation", async () => {
    vi.mocked(client.patchSettings).mockResolvedValue({
      ok: true,
      restart_required: ["port"],
    });
    wrap(<Settings />);

    fireEvent.click(await screen.findByTestId("int-inc-port"));

    fireEvent.click(screen.getByTestId("btn-save"));
    expect(client.patchSettings).not.toHaveBeenCalled(); // confirm-gated
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    await waitFor(() =>
      expect(client.patchSettings).toHaveBeenCalledWith(
        expect.objectContaining({ port: 8788 }),
        [],
      ),
    );
    expect(await screen.findByTestId("toast-success")).toBeInTheDocument();
  });

  it("toggles autostart off and includes it in the save", async () => {
    vi.mocked(client.patchSettings).mockResolvedValue({
      ok: true,
      restart_required: [],
    });
    wrap(<Settings />);

    const off = await screen.findByTestId("toggle-autostart-off");
    fireEvent.click(off);

    fireEvent.click(screen.getByTestId("btn-save"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    await waitFor(() =>
      expect(client.patchSettings).toHaveBeenCalledWith(
        expect.objectContaining({ autostart: false }),
        [],
      ),
    );
  });

  it("shows a field error from a 422", async () => {
    vi.mocked(client.patchSettings).mockRejectedValue({
      errors: [{ field: "port", message: "port must be 1–65535" }],
    });
    wrap(<Settings />);
    fireEvent.click(await screen.findByTestId("int-inc-port"));
    fireEvent.click(screen.getByTestId("btn-save"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));
    expect(await screen.findByTestId("field-error-port")).toHaveTextContent(
      "port must be 1–65535",
    );
  });

  it("a code-default field shows 'using code default' (no Override button)", async () => {
    vi.mocked(client.getSettingsEffective).mockResolvedValue(ALL_DEFAULT);
    wrap(<Settings />);
    expect(await screen.findByTestId("field-inherit-port")).toHaveTextContent(
      /using code default: 8787/i,
    );
    expect(screen.queryByTestId("field-override-port")).toBeNull();
  });

  it("reverting a file-sourced field stages an unset, persisted on Save", async () => {
    vi.mocked(client.getSettingsEffective).mockResolvedValue({
      ...ALL_DEFAULT,
      port: { value: 9000, source: "file" },
    });
    vi.mocked(client.patchSettings).mockResolvedValue({
      ok: true,
      restart_required: [],
    });
    wrap(<Settings />);

    fireEvent.click(await screen.findByTestId("field-inherit-port"));
    expect(client.patchSettings).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId("btn-save"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));
    await waitFor(() =>
      expect(client.patchSettings).toHaveBeenCalledWith({}, ["port"]),
    );
  });
});
