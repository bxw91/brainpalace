import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { SchemaForm } from "../SchemaForm";
import type { UiSchema, ConfigValues } from "../../../api/types";

function renderForm(props: {
  schema: UiSchema;
  values: ConfigValues;
  onSave?: (v: ConfigValues, restart: boolean) => void;
}) {
  const onSave = props.onSave ?? vi.fn();
  render(
    <SchemaForm schema={props.schema} values={props.values} onSave={onSave} />,
  );
  return onSave;
}

const dictSchema: UiSchema = {
  sections: [
    {
      key: "embedding",
      label: "Embedding",
      fields: [
        {
          key: "params",
          dotpath: "embedding.params",
          label: "Params",
          widget: "dict",
        },
      ],
    },
  ],
};

const listSchema: UiSchema = {
  sections: [
    {
      key: "git_indexing",
      label: "Git Indexing",
      fields: [
        {
          key: "path_filter",
          dotpath: "git_indexing.path_filter",
          label: "Path filter",
          widget: "stringlist",
        },
      ],
    },
  ],
};

describe("DictField", () => {
  it("renders existing key/value rows", () => {
    renderForm({
      schema: dictSchema,
      values: { embedding: { params: { temperature: "0.2" } } },
    });
    expect(
      (screen.getByTestId("dict-key-embedding.params-0") as HTMLInputElement).value,
    ).toBe("temperature");
    expect(
      (screen.getByTestId("dict-val-embedding.params-0") as HTMLInputElement).value,
    ).toBe("0.2");
  });

  it("adds an entry and saves it as a nested object", () => {
    const onSave = renderForm({
      schema: dictSchema,
      values: { embedding: {} },
    });
    fireEvent.click(screen.getByTestId("dict-add-embedding.params"));
    fireEvent.change(screen.getByTestId("dict-key-embedding.params-0"), {
      target: { value: "dimensions" },
    });
    fireEvent.change(screen.getByTestId("dict-val-embedding.params-0"), {
      target: { value: "256" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onSave).toHaveBeenCalledWith(
      { embedding: { params: { dimensions: "256" } } },
      false,
    );
  });

  it("removing the last entry emits undefined", () => {
    const onSave = renderForm({
      schema: dictSchema,
      values: { embedding: { params: { a: "1" } } },
    });
    fireEvent.click(screen.getByTestId("dict-remove-embedding.params-0"));
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onSave).toHaveBeenCalledWith({ embedding: { params: undefined } }, false);
  });
});

describe("StringListField", () => {
  it("renders existing items", () => {
    renderForm({
      schema: listSchema,
      values: { git_indexing: { path_filter: ["src/**"] } },
    });
    expect(
      (screen.getByTestId("stringlist-item-git_indexing.path_filter-0") as HTMLInputElement)
        .value,
    ).toBe("src/**");
  });

  it("adds an item and saves it as an array", () => {
    const onSave = renderForm({
      schema: listSchema,
      values: { git_indexing: {} },
    });
    fireEvent.click(screen.getByTestId("stringlist-add-git_indexing.path_filter"));
    fireEvent.change(
      screen.getByTestId("stringlist-item-git_indexing.path_filter-0"),
      { target: { value: "docs/**" } },
    );
    fireEvent.click(screen.getByRole("button", { name: /^save$/i }));
    expect(onSave).toHaveBeenCalledWith(
      { git_indexing: { path_filter: ["docs/**"] } },
      false,
    );
  });
});
