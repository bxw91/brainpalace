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
  onSave?: (v: ConfigValues, unset: string[], restart: boolean) => void;
  errors?: Record<string, string>;
  schema?: UiSchema;
  effective?: EffectiveConfig;
  inheritFrom?: "global" | "default";
  localSource?: "project" | "global" | "file";
}) {
  const onSave = props.onSave ?? vi.fn();
  render(
    <SchemaForm
      schema={props.schema ?? schema}
      values={props.values}
      effective={props.effective}
      onSave={onSave}
      errors={props.errors}
      inheritFrom={props.inheritFrom ?? "default"}
      localSource={props.localSource}
    />,
  );
  return onSave;
}

describe("SchemaForm inherit-first control", () => {
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

  it("inherit option shows the global value (only when a global value exists)", () => {
    renderForm({
      schema: provSchema,
      inheritFrom: "global",
      localSource: "project",
      values: { embedding: { provider: "openai" } }, // provider set locally
      effective: {
        "embedding.provider": {
          value: "openai",
          source: "project",
          inherited: { value: "ollama", source: "global" },
        },
        "embedding.base_url": { value: "http://host:11434", source: "global" },
      },
    });
    // Locally-set enum: inherit option present but unchecked; options visible.
    const provInherit = screen.getByTestId("field-inherit-embedding.provider");
    expect(provInherit).toHaveAttribute("aria-checked", "false");
    expect(provInherit).toHaveTextContent(/using global value: ollama/i);
    expect(screen.getByTestId("enum-embedding.provider-openai")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    // Inheriting text field with a global value: inherit option checked + the
    // input ALWAYS visible (no Override gate).
    const buInherit = screen.getByTestId("field-inherit-embedding.base_url");
    expect(buInherit).toHaveTextContent(
      /using global value: http:\/\/host:11434/i,
    );
    expect(buInherit).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("text-embedding.base_url")).toBeInTheDocument();
  });

  it("no global value → no inherit option, just the control", () => {
    renderForm({
      schema: provSchema,
      inheritFrom: "global",
      localSource: "project",
      values: {},
      effective: {
        // Only a code default, no global override → instance has nothing to inherit.
        "embedding.base_url": { value: "", source: "default" },
      },
    });
    expect(screen.queryByTestId("field-inherit-embedding.base_url")).toBeNull();
    expect(screen.getByTestId("text-embedding.base_url")).toBeInTheDocument();
  });

  it("selecting inherit on a locally-set key stages an unset (no immediate call)", () => {
    const onSave = renderForm({
      schema: provSchema,
      inheritFrom: "global",
      localSource: "project",
      values: { embedding: { provider: "ollama" } },
      effective: {
        "embedding.provider": {
          value: "ollama",
          source: "project",
          inherited: { value: "openai", source: "global" },
        },
      },
    });
    fireEvent.click(screen.getByTestId("field-inherit-embedding.provider"));
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    // provider reverted: omitted from values, present in the unset list.
    expect(onSave).toHaveBeenCalledWith({}, ["embedding.provider"], false);
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
    expect(
      screen.getByTestId("preset-embedding.model-text-embedding-3-large"),
    ).toBeTruthy();
    expect(
      screen.queryByTestId("preset-embedding.model-nomic-embed-text"),
    ).toBeNull();
    fireEvent.click(screen.getByTestId("enum-embedding.provider-ollama"));
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
    fireEvent.click(screen.getByTestId("enum-embedding.provider-ollama"));
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
    fireEvent.click(screen.getByTestId("enum-embedding.provider-ollama"));
    expect(onSave).not.toHaveBeenCalled(); // batched
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onSave).toHaveBeenCalledWith(
      { embedding: { provider: "ollama", api_key: "********" } },
      [],
      false,
    );
  });

  it("Save + Restart passes restart=true", () => {
    const onSave = renderForm({
      values: { embedding: { provider: "openai", api_key: "********" } },
    });
    fireEvent.click(screen.getByTestId("enum-embedding.provider-ollama"));
    fireEvent.click(screen.getByRole("button", { name: /save \+ restart/i }));
    expect(onSave).toHaveBeenCalledWith(
      { embedding: { provider: "ollama", api_key: "********" } },
      [],
      true,
    );
  });

  it("action bar is always shown; Save is disabled until dirty", () => {
    renderForm({ values: { embedding: { provider: "openai" } } });
    expect(screen.getByTestId("unsaved-banner")).toHaveTextContent(
      /no unsaved changes/i,
    );
    expect(screen.getByTestId("btn-save")).toBeDisabled();
    fireEvent.click(screen.getByTestId("enum-embedding.provider-ollama"));
    expect(screen.getByTestId("unsaved-banner")).toHaveTextContent(
      /1 unsaved change/i,
    );
    expect(screen.getByTestId("btn-save")).not.toBeDisabled();
  });

  it("Discard reverts an override back to the original", () => {
    const onSave = renderForm({ values: { embedding: { provider: "openai" } } });
    fireEvent.click(screen.getByTestId("enum-embedding.provider-ollama"));
    fireEvent.click(screen.getByRole("button", { name: /discard/i }));
    expect(screen.getByTestId("unsaved-banner")).toHaveTextContent(
      /no unsaved changes/i,
    );
    expect(screen.getByTestId("enum-embedding.provider-openai")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(onSave).not.toHaveBeenCalled();
  });

  it("Discard reverts a staged inherit too", () => {
    renderForm({
      inheritFrom: "global",
      localSource: "project",
      values: { embedding: { provider: "openai" } },
      effective: {
        "embedding.provider": {
          value: "openai",
          source: "project",
          inherited: { value: "ollama", source: "global" },
        },
      },
    });
    // Revert to inherit -> dirty; Discard -> back to the override.
    fireEvent.click(screen.getByTestId("field-inherit-embedding.provider"));
    expect(screen.getByTestId("unsaved-banner")).toHaveTextContent(
      /1 unsaved change/i,
    );
    fireEvent.click(screen.getByRole("button", { name: /discard/i }));
    expect(screen.getByTestId("unsaved-banner")).toHaveTextContent(
      /no unsaved changes/i,
    );
    expect(screen.getByTestId("enum-embedding.provider-openai")).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("renders a secret text field masked (type=password)", () => {
    renderForm({
      values: { embedding: { provider: "openai", api_key: "********" } },
    });
    const group = screen.getByTestId("field-embedding.api_key");
    const input = group.querySelector("input");
    expect(input).toHaveAttribute("type", "password");
  });

  it("renders a toggle as On/Off radios and batches its change", () => {
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
    fireEvent.click(screen.getByTestId("toggle-graphrag.enabled-on"));
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onSave).toHaveBeenCalledWith(
      { graphrag: { enabled: true } },
      [],
      false,
    );
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
    fireEvent.click(screen.getByTestId("int-inc-query.top_k"));
    fireEvent.click(screen.getByTestId("int-dec-query.top_k"));
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onSave).toHaveBeenCalledWith({ query: { top_k: 2 } }, [], false);
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
              key: "quiescence_seconds",
              dotpath: "session_extraction.quiescence_seconds",
              label: "Quiescence seconds",
              widget: "int",
              options: [],
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

  it("surfaces the code default on the inherit option when unset", () => {
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
          ],
        },
      ],
    };
    renderForm({
      schema: defSchema,
      values: {},
      effective: {
        "storage.backend": { value: "chroma", source: "default", inherited: null },
      },
    });
    const inherit = screen.getByTestId("field-inherit-storage.backend");
    expect(inherit).toHaveTextContent(/using code default: chroma/i);
    expect(inherit).toHaveAttribute("aria-checked", "true");
  });
});
