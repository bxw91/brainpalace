import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { SchemaForm } from "./SchemaForm";
import type { UiSchema, ConfigValues } from "../../api/types";

const schema: UiSchema = {
  sections: [
    {
      key: "embedding",
      label: "Embedding",
      fields: [
        {
          key: "provider",
          dotpath: "embedding.provider",
          label: "Provider",
          widget: "enum",
          options: ["openai", "ollama"],
        },
        {
          key: "api_key",
          dotpath: "embedding.api_key",
          label: "API key",
          widget: "text",
          secret: true,
        },
      ],
    },
  ],
};

function renderForm(props: {
  values: ConfigValues;
  onSave?: (v: ConfigValues, restart: boolean) => void;
  errors?: Record<string, string>;
  schema?: UiSchema;
}) {
  const onSave = props.onSave ?? vi.fn();
  render(
    <SchemaForm
      schema={props.schema ?? schema}
      values={props.values}
      onSave={onSave}
      errors={props.errors}
    />,
  );
  return onSave;
}

describe("SchemaForm", () => {
  it("renders enum as buttons and batches a single save payload", () => {
    const onSave = renderForm({
      values: { embedding: { provider: "openai", api_key: "********" } },
    });
    fireEvent.click(screen.getByRole("button", { name: "ollama" }));
    expect(onSave).not.toHaveBeenCalled(); // batched
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onSave).toHaveBeenCalledWith(
      { embedding: { provider: "ollama", api_key: "********" } },
      false,
    );
  });

  it("enum has no free-text input", () => {
    renderForm({ values: { embedding: { provider: "openai" } } });
    const providerGroup = screen.getByTestId("field-embedding.provider");
    expect(providerGroup.querySelector("input[type=text]")).toBeNull();
  });

  it("Save + Restart passes restart=true", () => {
    const onSave = renderForm({
      values: { embedding: { provider: "openai", api_key: "********" } },
    });
    fireEvent.click(screen.getByRole("button", { name: "ollama" }));
    fireEvent.click(screen.getByRole("button", { name: /save \+ restart/i }));
    expect(onSave).toHaveBeenCalledWith(
      { embedding: { provider: "ollama", api_key: "********" } },
      true,
    );
  });

  it("action bar is always shown; Save is disabled until dirty", () => {
    renderForm({ values: { embedding: { provider: "openai" } } });
    // Always visible for discoverability, but Save is disabled while clean.
    expect(screen.getByTestId("unsaved-banner")).toHaveTextContent(
      /no unsaved changes/i,
    );
    expect(screen.getByTestId("btn-save")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "ollama" }));
    expect(screen.getByTestId("unsaved-banner")).toHaveTextContent(
      /1 unsaved change/i,
    );
    expect(screen.getByTestId("btn-save")).not.toBeDisabled();
  });

  it("Discard reverts the draft to the original values", () => {
    const onSave = renderForm({ values: { embedding: { provider: "openai" } } });
    fireEvent.click(screen.getByRole("button", { name: "ollama" }));
    fireEvent.click(screen.getByRole("button", { name: /discard/i }));
    // Bar stays (always visible) but reverts to the clean state.
    expect(screen.getByTestId("unsaved-banner")).toHaveTextContent(
      /no unsaved changes/i,
    );
    // provider button "openai" is selected again
    expect(screen.getByRole("button", { name: "openai" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(onSave).not.toHaveBeenCalled();
  });

  it("renders a secret text field masked (type=password)", () => {
    renderForm({
      values: { embedding: { provider: "openai", api_key: "********" } },
    });
    const group = screen.getByTestId("field-embedding.api_key");
    const input = group.querySelector("input");
    expect(input).toHaveAttribute("type", "password");
  });

  it("renders a toggle and batches its change", () => {
    const toggleSchema: UiSchema = {
      sections: [
        {
          key: "graphrag",
          label: "GraphRAG",
          fields: [
            {
              key: "enabled",
              dotpath: "graphrag.enabled",
              label: "Enabled",
              widget: "toggle",
            },
          ],
        },
      ],
    };
    const onSave = renderForm({
      schema: toggleSchema,
      values: { graphrag: { enabled: false } },
    });
    fireEvent.click(screen.getByTestId("toggle-graphrag.enabled"));
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onSave).toHaveBeenCalledWith({ graphrag: { enabled: true } }, false);
  });

  it("clamps an int stepper to min/max", () => {
    const intSchema: UiSchema = {
      sections: [
        {
          key: "query",
          label: "Query",
          fields: [
            {
              key: "top_k",
              dotpath: "query.top_k",
              label: "Top K",
              widget: "int",
              min: 1,
              max: 3,
              step: 1,
            },
          ],
        },
      ],
    };
    const onSave = renderForm({
      schema: intSchema,
      values: { query: { top_k: 3 } },
    });
    // increment beyond max stays at 3
    fireEvent.click(screen.getByTestId("int-inc-query.top_k"));
    fireEvent.click(screen.getByTestId("int-dec-query.top_k"));
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onSave).toHaveBeenCalledWith({ query: { top_k: 2 } }, false);
  });

  it("preset field hides the text input until Custom is chosen", () => {
    const presetSchema: UiSchema = {
      sections: [
        {
          key: "embedding",
          label: "Embedding",
          fields: [
            {
              key: "model",
              dotpath: "embedding.model",
              label: "Model",
              widget: "text",
              presets: ["text-embedding-3-small", "text-embedding-3-large"],
            },
          ],
        },
      ],
    };
    renderForm({
      schema: presetSchema,
      values: { embedding: { model: "text-embedding-3-small" } },
    });
    const group = screen.getByTestId("field-embedding.model");
    // a preset is selected -> no free text input visible
    expect(group.querySelector("input[type=text]")).toBeNull();
    fireEvent.click(within(group).getByRole("button", { name: /custom/i }));
    expect(group.querySelector("input[type=text]")).not.toBeNull();
  });

  it("renders an inline error under the right field", () => {
    renderForm({
      values: { embedding: { provider: "openai" } },
      errors: { "embedding.provider": "must be a valid provider" },
    });
    const group = screen.getByTestId("field-embedding.provider");
    expect(within(group).getByTestId("field-error-embedding.provider")).toHaveTextContent(
      "must be a valid provider",
    );
  });

  it("surfaces defaults: label hint + the default enum option marked when unset", () => {
    const defSchema: UiSchema = {
      sections: [
        {
          key: "storage",
          label: "Storage",
          fields: [
            {
              key: "backend",
              dotpath: "storage.backend",
              label: "Backend",
              widget: "enum",
              options: ["chroma", "postgres"],
              default: "chroma",
            },
            {
              key: "watch_debounce_ms",
              dotpath: "session_indexing.watch_debounce_ms",
              label: "Watch debounce ms",
              widget: "int",
              min: 0,
              default: 30000,
            },
          ],
        },
      ],
    };
    // Nothing set -> defaults are surfaced.
    renderForm({ schema: defSchema, values: {} });

    // Label hint shows the default.
    expect(
      screen.getByTestId("field-default-storage.backend"),
    ).toHaveTextContent("default: chroma");
    // The default enum option is marked while unset, but NOT "selected".
    const chroma = screen.getByTestId("enum-storage.backend-chroma");
    expect(chroma).toHaveAttribute("data-selected", "false");
    expect(chroma).toHaveTextContent(/default/i);
    // Unset int shows the default value (30000), not 0.
    expect(
      screen.getByTestId("int-value-session_indexing.watch_debounce_ms"),
    ).toHaveTextContent("30000");
  });
});
