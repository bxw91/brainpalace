import {
  render,
  screen,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Logs } from "./Logs";
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
  vi.mocked(client.getLogs).mockResolvedValue({
    lines: ["2026-06-06 INFO booted", "2026-06-06 ERROR boom"],
  });
});

describe("Logs tab", () => {
  it("renders log lines", async () => {
    wrap(<Logs instanceId="a" />);
    expect(await screen.findByText(/INFO booted/)).toBeInTheDocument();
    const pane = within(screen.getByTestId("log-pane"));
    expect(pane.getByText(/ERROR boom/)).toBeInTheDocument();
  });

  it("level filter re-queries with the level", async () => {
    wrap(<Logs instanceId="a" />);
    await screen.findByText(/INFO booted/);
    fireEvent.change(screen.getByTestId("select-log-level"), {
      target: { value: "ERROR" },
    });
    await waitFor(() => {
      const calls = vi.mocked(client.getLogs).mock.calls;
      const last = calls[calls.length - 1];
      expect(last[2]).toBe("ERROR");
    });
  });

  it("lines selector re-queries with the count", async () => {
    wrap(<Logs instanceId="a" />);
    await screen.findByText(/INFO booted/);
    fireEvent.click(screen.getByTestId("btn-lines-500"));
    await waitFor(() => {
      const calls = vi.mocked(client.getLogs).mock.calls;
      const last = calls[calls.length - 1];
      expect(last[1]).toBe(500);
    });
  });

  it("has an auto-tail toggle", async () => {
    wrap(<Logs instanceId="a" />);
    await screen.findByText(/INFO booted/);
    const toggle = screen.getByTestId("btn-autotail");
    expect(toggle).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
  });

  it("shows stopped state when unreachable", async () => {
    vi.mocked(client.getLogs).mockRejectedValue(
      new client.InstanceUnreachableError("down", 502),
    );
    wrap(<Logs instanceId="a" />);
    expect(await screen.findByTestId("logs-stopped")).toBeInTheDocument();
  });

  it("shows an error state with retry on a non-unreachable failure", async () => {
    vi.mocked(client.getLogs).mockRejectedValue(new Error("logs 500"));
    wrap(<Logs instanceId="a" />);
    expect(await screen.findByTestId("logs-error")).toBeInTheDocument();
    expect(screen.getByText(/logs 500/)).toBeInTheDocument();
    expect(screen.getByTestId("logs-error-retry")).toBeInTheDocument();
  });

  it("shows the empty log message when there are no lines", async () => {
    vi.mocked(client.getLogs).mockResolvedValue({ lines: [] });
    wrap(<Logs instanceId="a" />);
    expect(await screen.findByText(/no log lines/i)).toBeInTheDocument();
  });
});
