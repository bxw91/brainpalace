import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Config } from "./Config";
import { ToastProvider } from "../components/Toast";
import * as client from "../api/client";

vi.mock("../api/client");

const schema = {
  sections: [
    {
      key: "embedding",
      label: "Embedding",
      fields: [
        {
          key: "provider",
          dotpath: "embedding.provider",
          label: "Provider",
          widget: "enum" as const,
          options: ["openai", "ollama"],
        },
      ],
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
  vi.mocked(client.getSchema).mockResolvedValue(schema as never);
  vi.mocked(client.getConfig).mockResolvedValue({
    embedding: { provider: "openai" },
  } as never);
});

describe("Config tab", () => {
  it("Save sends patchConfig(id, values, false)", async () => {
    vi.mocked(client.patchConfig).mockResolvedValue({
      ok: true,
      restarted: false,
    });
    wrap(<Config instanceId="inst-1" />);

    await screen.findByRole("button", { name: "ollama" });
    fireEvent.click(screen.getByRole("button", { name: "ollama" }));
    fireEvent.click(screen.getByTestId("btn-save"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    await waitFor(() =>
      expect(client.patchConfig).toHaveBeenCalledWith(
        "inst-1",
        { embedding: { provider: "ollama" } },
        false,
        false,
      ),
    );
  });

  it("renders a 422 validation error inline under the field", async () => {
    vi.mocked(client.patchConfig).mockRejectedValue({
      errors: [
        { field: "embedding.provider", message: "unsupported provider" },
      ],
    });
    wrap(<Config instanceId="inst-1" />);

    await screen.findByRole("button", { name: "ollama" });
    fireEvent.click(screen.getByRole("button", { name: "ollama" }));
    fireEvent.click(screen.getByTestId("btn-save"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    const err = await screen.findByTestId("field-error-embedding.provider");
    expect(err).toHaveTextContent("unsupported provider");
  });

  it("Save + Restart sends restart=true and shows a success toast", async () => {
    vi.mocked(client.patchConfig).mockResolvedValue({
      ok: true,
      restarted: true,
    });
    wrap(<Config instanceId="inst-1" />);

    await screen.findByRole("button", { name: "ollama" });
    fireEvent.click(screen.getByRole("button", { name: "ollama" }));
    fireEvent.click(screen.getByTestId("btn-save-restart"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    await waitFor(() =>
      expect(client.patchConfig).toHaveBeenCalledWith(
        "inst-1",
        { embedding: { provider: "ollama" } },
        true,
        false,
      ),
    );
    expect(await screen.findByTestId("toast-success")).toBeInTheDocument();
  });

  it("shows the conflict dialog on 409 and re-PATCHes with force on reindex", async () => {
    const conflict = {
      conflict: "data_incompatible" as const,
      message: "incompatible",
      fields: [{ dotpath: "embedding.provider", current: "openai", new: "ollama" }],
      counts: { documents: 10, chunks: 99 },
    };
    vi.mocked(client.patchConfig)
      .mockRejectedValueOnce(conflict)
      .mockResolvedValueOnce({ ok: true, reindex_triggered: 2 });
    wrap(<Config instanceId="inst-1" />);

    await screen.findByRole("button", { name: "ollama" });
    fireEvent.click(screen.getByRole("button", { name: "ollama" }));
    fireEvent.click(screen.getByTestId("btn-save"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    const dialog = await screen.findByTestId("data-conflict-dialog");
    expect(dialog).toHaveTextContent("incompatible");
    fireEvent.click(screen.getByTestId("conflict-reindex"));

    await waitFor(() => expect(client.patchConfig).toHaveBeenCalledTimes(2));
    expect(vi.mocked(client.patchConfig).mock.calls[1]).toEqual([
      "inst-1",
      { embedding: { provider: "ollama" } },
      false,
      true,
    ]);
  });

  it("shows an error state with retry when the config load fails", async () => {
    vi.mocked(client.getConfig).mockRejectedValue(new Error("cfg 500"));
    wrap(<Config instanceId="inst-1" />);
    const retry = await screen.findByTestId("config-error-retry");
    expect(retry).toBeInTheDocument();
    expect(screen.getByText(/cfg 500/)).toBeInTheDocument();
    // Retry re-runs the loaders.
    vi.mocked(client.getConfig).mockResolvedValue({
      embedding: { provider: "openai" },
    } as never);
    fireEvent.click(retry);
    expect(await screen.findByRole("button", { name: "ollama" })).toBeInTheDocument();
  });
});
