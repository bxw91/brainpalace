import { render, screen, fireEvent, within } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { SchemaForm } from "./SchemaForm";
import type { UiSchema, ConfigValues, EffectiveConfig } from "../../api/types";

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
  effective?: EffectiveConfig;
  onUnset?: (dotpath: string) => void;
}) {
  const onSave = props.onSave ?? vi.fn();
  render(
    <SchemaForm
      schema={props.schema ?? schema}
      values={props.values}
      effective={props.effective}
      onSave={onSave}
      errors={props.errors}
      onUnset={props.onUnset}
    />,
  );
  return onSave;
}

describe("SchemaForm provenance", () => {
  const provSchema: UiSchema = {
    sections: [
      {
        key: "embedding",
        label: "Embedding",
        fields: [
          { key: "provider", dotpath: "embedding.provider", label: "Provider",
            widget: "enum", options: ["openai", "ollama"] },
          { key: "base_url", dotpath: "embedding.base_url", label: "Base URL",
            widget: "text" },
        ],
      },
    ],
  };

  it("shows provenance only for unset fields; nothing for locally-set ones", () => {
    renderForm({
      schema: provSchema,
      values: { embedding: { provider: "openai" } }, // provider set locally
      effective: {
        "embedding.provider": { value: "openai", source: "project" },
        "embedding.base_url": { value: "http://host:11434", source: "global" },
      },
    });
    // Locally-set field: no default/inherited hint.
    expect(
      screen.queryByTestId("field-default-embedding.provider"),
    ).toBeNull();
    // Unset field inheriting from global: hint shows the global value, input empty.
    expect(
      screen.getByTestId("field-default-embedding.base_url"),
    ).toHaveTextContent("inherited from global: http://host:11434");
    expect(
      (screen.getByTestId("text-embedding.base_url") as HTMLInputElement).value,
    ).toBe("");
  });

  it("shows a source badge per field and an unset control on project-set keys", () => {
    const onUnset = vi.fn();
    renderForm({
      schema: provSchema,
      values: { embedding: { provider: "ollama" } },
      effective: {
        // project-set, would inherit the global value if unset
        "embedding.provider": {
          value: "ollama",
          source: "project",
          inherited: { value: "openai", source: "global" },
        },
        "embedding.base_url": { value: "http://host:11434", source: "global" },
      },
      onUnset,
    });
    // Source badges reflect provenance.
    expect(
      screen.getByTestId("field-source-embedding.provider"),
    ).toHaveTextContent("project");
    expect(
      screen.getByTestId("field-source-embedding.base_url"),
    ).toHaveTextContent("global");
    // Unset control only on the project-set field; shows the inherited target.
    const unset = screen.getByTestId("field-unset-embedding.provider");
    expect(unset).toHaveTextContent("openai from global");
    expect(
      screen.queryByTestId("field-unset-embedding.base_url"),
    ).toBeNull();
    fireEvent.click(unset);
    expect(onUnset).toHaveBeenCalledWith("embedding.provider");
  });
});

describe("SchemaForm provider-driven rendering", () => {
  const providers = {
    embedding: {
      openai: {
        models: ["text-embedding-3-large", "text-embedding-3-small"],
        needs_base_url: false,
        default_api_key_env: "OPENAI_API_KEY",
      },
      ollama: {
        models: ["nomic-embed-text", "mxbai-embed-large"],
        needs_base_url: true,
        default_api_key_env: null,
      },
    },
  };
  const provDriveSchema: UiSchema = {
    providers,
    sections: [
      {
        key: "embedding",
        label: "Embedding",
        fields: [
          { key: "provider", dotpath: "embedding.provider", label: "Provider",
            widget: "enum", options: ["openai", "ollama"] },
          { key: "model", dotpath: "embedding.model", label: "Model",
            widget: "text", presets: [] },
          { key: "base_url", dotpath: "embedding.base_url", label: "Base URL",
            widget: "text" },
          { key: "api_key_env", dotpath: "embedding.api_key_env",
            label: "API key env var", widget: "text" },
        ],
      },
    ],
  };

  it("model presets follow the selected provider", () => {
    renderForm({
      schema: provDriveSchema,
      values: { embedding: { provider: "openai" } },
    });
    // openai's models are the presets
    expect(
      screen.getByTestId("preset-embedding.model-text-embedding-3-large"),
    ).toBeTruthy();
    expect(
      screen.queryByTestId("preset-embedding.model-nomic-embed-text"),
    ).toBeNull();
    // switch to ollama -> presets change
    fireEvent.click(screen.getByRole("button", { name: "ollama" }));
    expect(
      screen.getByTestId("preset-embedding.model-nomic-embed-text"),
    ).toBeTruthy();
    expect(
      screen.queryByTestId("preset-embedding.model-text-embedding-3-large"),
    ).toBeNull();
  });

  it("base_url is hidden for openai and shown for ollama", () => {
    renderForm({
      schema: provDriveSchema,
      values: { embedding: { provider: "openai" } },
    });
    expect(screen.queryByTestId("field-embedding.base_url")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "ollama" }));
    expect(screen.getByTestId("field-embedding.base_url")).toBeTruthy();
  });

  it("api_key_env placeholder follows the provider's default env var", () => {
    renderForm({
      schema: provDriveSchema,
      values: { embedding: { provider: "openai" } },
    });
    expect(
      screen.getByTestId("text-embedding.api_key_env"),
    ).toHaveAttribute("placeholder", "OPENAI_API_KEY");
  });
});

describe("SchemaForm secret fields", () => {
  const secretSchema: UiSchema = {
    sections: [
      {
        key: "embedding",
        label: "Embedding",
        fields: [
          { key: "api_key", dotpath: "embedding.api_key", label: "API key",
            widget: "text", secret: true },
        ],
      },
    ],
  };

  it("shows masking dots only when a secret is set", () => {
    renderForm({ schema: secretSchema, values: { embedding: { api_key: "********" } } });
    expect(screen.getByTestId("text-embedding.api_key")).toHaveAttribute(
      "placeholder",
      "••••••••",
    );
  });

  it("shows NO masking dots when the secret is unset (empty)", () => {
    renderForm({ schema: secretSchema, values: { embedding: {} } });
    const input = screen.getByTestId("text-embedding.api_key") as HTMLInputElement;
    expect(input.placeholder).toBe("");
  });
});

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

  it("renders the section description when present", () => {
    const descSchema: UiSchema = {
      sections: [
        {
          key: "session_extraction",
          label: "Session Extraction",
          description: "Distills a finished chat into a summary.",
          fields: [
            {
              key: "mode",
              dotpath: "session_extraction.mode",
              label: "Mode",
              widget: "enum",
              options: ["subagent", "off"],
            },
          ],
        },
      ],
    };
    renderForm({ schema: descSchema, values: {} });
    expect(
      screen.getByTestId("section-desc-session_extraction"),
    ).toHaveTextContent("Distills a finished chat");
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
    // Unset int is EMPTY (— placeholder); the default is shown beside the label,
    // never baked into the input.
    expect(
      screen.getByTestId("int-value-session_indexing.watch_debounce_ms"),
    ).toHaveTextContent("—");
    expect(
      screen.getByTestId("field-default-session_indexing.watch_debounce_ms"),
    ).toHaveTextContent("default: 30000");
  });
});
