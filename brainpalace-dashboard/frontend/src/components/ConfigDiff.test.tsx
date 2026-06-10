import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ConfigDiff } from "./ConfigDiff";
import * as client from "../api/client";
import type { EffectiveConfig } from "../api/types";

vi.mock("../api/client");

const cfgA: EffectiveConfig = {
  "embedding.provider": { value: "openai", source: "global" },
  "bm25.language": { value: "en", source: "default" },
};
const cfgB: EffectiveConfig = {
  "embedding.provider": { value: "ollama", source: "project" },
  "bm25.language": { value: "en", source: "default" },
};

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ConfigDiff
        instanceId="a"
        instances={[
          { id: "a", name: "proj-a" },
          { id: "b", name: "proj-b" },
        ]}
      />
    </QueryClientProvider>,
  );
}

describe("ConfigDiff", () => {
  beforeEach(() => {
    vi.mocked(client.getConfigEffective).mockImplementation(async (id: string) =>
      id === "a" ? cfgA : cfgB,
    );
  });

  it("shows only differing keys after picking a comparison instance", async () => {
    mount();
    fireEvent.change(screen.getByTestId("select-diff-instance"), {
      target: { value: "b" },
    });
    expect(await screen.findByText("embedding.provider")).toBeInTheDocument();
    expect(screen.queryByText("bm25.language")).toBeNull();
  });
});
