import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

// CommandPalette imports TABS from ../router; mock the module so the test
// doesn't load the real router (module-level createRouter + every tab).
vi.mock("../router", () => ({
  TABS: [
    { path: "/", label: "Overview", scope: "fleet" },
    { path: "/queries", label: "Queries", scope: "instance" },
    { path: "/logs", label: "Logs", scope: "instance" },
  ],
}));

import { CommandPalette } from "./CommandPalette";

describe("CommandPalette", () => {
  it("opens on Cmd/Ctrl+K, filters, and navigates on Enter", () => {
    const onNavigate = vi.fn();
    render(<CommandPalette onNavigate={onNavigate} />);
    expect(screen.queryByTestId("command-palette")).toBeNull();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByTestId("command-palette")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
    fireEvent.change(screen.getByTestId("palette-input"), {
      target: { value: "que" },
    });
    fireEvent.keyDown(screen.getByTestId("palette-input"), { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith("/queries");
    expect(screen.queryByTestId("command-palette")).toBeNull();
  });

  it("closes on Escape", () => {
    render(<CommandPalette onNavigate={vi.fn()} />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("command-palette")).toBeNull();
  });
});
