import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Sidebar } from "./Sidebar";
import type { Instance } from "../api/types";

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

describe("Sidebar", () => {
  it("renders instances with status dots", () => {
    render(
      <Sidebar
        instances={[
          inst({ id: "a", name: "foo", status: "running" }),
          inst({ id: "b", name: "bar", status: "stopped" }),
        ]}
        selectedId="a"
        onSelect={() => {}}
      />,
    );
    expect(screen.getByText("foo")).toBeInTheDocument();
    expect(screen.getByText("bar")).toBeInTheDocument();
    expect(screen.getByTestId("status-a")).toHaveAttribute("data-status", "running");
    expect(screen.getByTestId("status-b")).toHaveAttribute("data-status", "stopped");
  });

  it("fires onSelect when an instance row is clicked", () => {
    const onSelect = vi.fn();
    render(
      <Sidebar
        instances={[inst({ id: "a", name: "foo", status: "running" })]}
        selectedId={null}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByTestId("instance-row-a"));
    expect(onSelect).toHaveBeenCalledWith("a");
  });

  it("shows an empty state when there are no instances", () => {
    render(<Sidebar instances={[]} selectedId={null} onSelect={() => {}} />);
    expect(screen.getByTestId("sidebar-empty")).toBeInTheDocument();
  });
});
