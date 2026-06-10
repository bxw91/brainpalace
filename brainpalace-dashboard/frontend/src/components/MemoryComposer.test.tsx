import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryComposer } from "./MemoryComposer";
import { ToastProvider } from "./Toast";
import * as client from "../api/client";

vi.mock("../api/client");

function mount() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryComposer instanceId="i1" />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("MemoryComposer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.memoryCreate).mockResolvedValue({ ok: true } as never);
  });

  it("disables Save while the text input is empty", () => {
    mount();
    expect(screen.getByTestId("btn-memory-save")).toBeDisabled();
    fireEvent.change(screen.getByTestId("input-memory-text"), {
      target: { value: "   " },
    });
    expect(screen.getByTestId("btn-memory-save")).toBeDisabled();
  });

  it("saves trimmed text + section via memoryCreate", async () => {
    mount();
    fireEvent.change(screen.getByTestId("input-memory-text"), {
      target: { value: "  remember the port range  " },
    });
    fireEvent.change(screen.getByTestId("input-memory-section"), {
      target: { value: "infra" },
    });
    fireEvent.click(screen.getByTestId("btn-memory-save"));
    await waitFor(() =>
      expect(client.memoryCreate).toHaveBeenCalledWith("i1", {
        text: "remember the port range",
        section: "infra",
      }),
    );
  });

  it("clears the text input after a successful save", async () => {
    mount();
    const input = screen.getByTestId("input-memory-text");
    fireEvent.change(input, { target: { value: "ephemeral note" } });
    fireEvent.click(screen.getByTestId("btn-memory-save"));
    await waitFor(() => expect(input).toHaveValue(""));
  });
});
