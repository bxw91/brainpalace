import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { GlobalConfig } from "./GlobalConfig";
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
  vi.mocked(client.getGlobalConfig).mockResolvedValue({
    embedding: { provider: "openai" },
  } as never);
});

describe("GlobalConfig tab (Server page)", () => {
  it("saves the global config via patchGlobalConfig (no restart button)", async () => {
    vi.mocked(client.patchGlobalConfig).mockResolvedValue({ ok: true });
    wrap(<GlobalConfig />);

    await screen.findByRole("button", { name: "ollama" });
    // Global config has no instance to restart.
    expect(screen.queryByTestId("btn-save-restart")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "ollama" }));
    fireEvent.click(screen.getByTestId("btn-save"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    await waitFor(() =>
      expect(client.patchGlobalConfig).toHaveBeenCalledWith(
        { embedding: { provider: "ollama" } },
        false,
      ),
    );
    expect(await screen.findByTestId("toast-success")).toBeInTheDocument();
  });

  it("renders a 422 validation error inline", async () => {
    vi.mocked(client.patchGlobalConfig).mockRejectedValue({
      errors: [{ field: "embedding.provider", message: "unsupported provider" }],
    });
    wrap(<GlobalConfig />);

    await screen.findByRole("button", { name: "ollama" });
    fireEvent.click(screen.getByRole("button", { name: "ollama" }));
    fireEvent.click(screen.getByTestId("btn-save"));
    fireEvent.click(await screen.findByTestId("btn-confirm"));

    expect(
      await screen.findByTestId("field-error-embedding.provider"),
    ).toHaveTextContent("unsupported provider");
  });
});
