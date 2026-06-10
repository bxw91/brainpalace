import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DecisionTimeline } from "./DecisionTimeline";
import * as client from "../api/client";

vi.mock("../api/client");

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DecisionTimeline instanceId="i1" />
    </QueryClientProvider>,
  );
}

describe("DecisionTimeline", () => {
  beforeEach(() => {
    vi.mocked(client.getDecisions).mockResolvedValue({
      decisions: [{ id: "d1", name: "use poetry", label: "Decision" }],
    });
    vi.mocked(client.getDecisionTimeline).mockResolvedValue({
      entity: "use poetry",
      timeline: [
        {
          subject: "use uv",
          predicate: "supersedes",
          object: "use poetry",
          valid_from: "2026-03-01T00:00:00",
          valid_until: null,
          valid: true,
        },
        {
          subject: "use poetry",
          predicate: "affects",
          object: "pyproject.toml",
          valid_from: "2026-01-01T00:00:00",
          valid_until: "2026-03-01T00:00:00",
          valid: false,
        },
      ],
    });
  });

  it("lists decisions and opens an entity timeline with validity badges", async () => {
    mount();
    fireEvent.click(await screen.findByText("use poetry"));
    expect(await screen.findByTestId("timeline-rows")).toBeInTheDocument();
    expect(screen.getByText("supersedes")).toBeInTheDocument();
    expect(screen.getAllByTestId("badge-superseded")).toHaveLength(1);
  });

  it("passes the typed search text to getDecisions as contains", async () => {
    mount();
    await screen.findByText("use poetry");
    fireEvent.change(screen.getByTestId("input-decision-search"), {
      target: { value: "poetry" },
    });
    await waitFor(() =>
      expect(client.getDecisions).toHaveBeenCalledWith("i1", "poetry"),
    );
  });

  it("shows a no-match empty state when a search returns nothing", async () => {
    mount();
    await screen.findByText("use poetry");
    vi.mocked(client.getDecisions).mockResolvedValue({ decisions: [] });
    fireEvent.change(screen.getByTestId("input-decision-search"), {
      target: { value: "nope" },
    });
    expect(
      await screen.findByText(/No decisions match "nope"\./),
    ).toBeInTheDocument();
  });

  it("labels the timeline with the selected entity and clears it", async () => {
    mount();
    fireEvent.click(await screen.findByText("use poetry"));
    expect(await screen.findByText(/Timeline — use poetry/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Clear selection"));
    expect(screen.queryByText(/Timeline — use poetry/)).not.toBeInTheDocument();
    expect(screen.queryByTestId("timeline-rows")).not.toBeInTheDocument();
  });
});
