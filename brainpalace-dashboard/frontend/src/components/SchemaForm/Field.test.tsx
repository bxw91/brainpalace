import { render, screen, fireEvent } from "@testing-library/react";
import { test, expect, vi } from "vitest";
import { Field } from "./Field";
import type { SchemaField, EffectiveConfig } from "../../api/types";

const enumField: SchemaField = {
  key: "provider",
  dotpath: "embedding.provider",
  label: "Provider",
  widget: "enum",
  options: ["openai", "cohere", "ollama"],
  default: "openai",
};

function renderField(opts: {
  eff: EffectiveConfig;
  field?: SchemaField;
  localSource?: "project" | "global" | "file";
  inheritFrom?: "global" | "default";
  raw?: unknown;
  onInherit?: (d: string) => void;
  setValue?: (d: string, v: unknown) => void;
}) {
  return render(
    <Field
      field={opts.field ?? enumField}
      getValue={() => opts.raw}
      setValue={opts.setValue ?? (() => {})}
      effective={opts.eff}
      onInherit={opts.onInherit ?? (() => {})}
      localSource={opts.localSource}
      inheritFrom={opts.inheritFrom ?? "global"}
    />,
  );
}

test("inheriting from global: inherit option shows 'using global value: X' and is checked", () => {
  renderField({
    eff: {
      "embedding.provider": { value: "cohere", source: "global", inherited: null },
    },
    localSource: "project",
    inheritFrom: "global",
    raw: undefined,
  });
  const inherit = screen.getByTestId("field-inherit-embedding.provider");
  expect(inherit).toHaveTextContent(/using global value: cohere/i);
  expect(inherit).toHaveAttribute("aria-checked", "true");
  // All enum options are visible inline, unchecked while inheriting.
  expect(screen.getByTestId("enum-embedding.provider-openai")).toHaveAttribute(
    "aria-checked",
    "false",
  );
});

test("selecting an enum option stages an override via setValue", () => {
  const setValue = vi.fn();
  renderField({
    eff: {
      "embedding.provider": { value: "cohere", source: "global", inherited: null },
    },
    localSource: "project",
    raw: undefined,
    setValue,
  });
  fireEvent.click(screen.getByTestId("enum-embedding.provider-ollama"));
  expect(setValue).toHaveBeenCalledWith("embedding.provider", "ollama");
});

test("selecting the inherit option reverts via onInherit (no value set)", () => {
  const onInherit = vi.fn();
  const setValue = vi.fn();
  renderField({
    eff: {
      "embedding.provider": {
        value: "cohere",
        source: "project",
        inherited: { value: "openai", source: "global" },
      },
    },
    localSource: "project",
    inheritFrom: "global",
    raw: "cohere", // overridden locally
    onInherit,
    setValue,
  });
  const inherit = screen.getByTestId("field-inherit-embedding.provider");
  // While overridden, the inherit option is unchecked and previews the target.
  expect(inherit).toHaveAttribute("aria-checked", "false");
  expect(inherit).toHaveTextContent(/using global value: openai/i);
  fireEvent.click(inherit);
  expect(onInherit).toHaveBeenCalledWith("embedding.provider");
  expect(setValue).not.toHaveBeenCalled();
});

test("global tab: inherit option reads 'using code default: X'", () => {
  renderField({
    eff: {
      "embedding.provider": { value: "openai", source: "default", inherited: null },
    },
    localSource: "global",
    inheritFrom: "default",
    raw: undefined,
  });
  expect(
    screen.getByTestId("field-inherit-embedding.provider"),
  ).toHaveTextContent(/using code default: openai/i);
});

test("instance tab, no global value → inherit falls back to the code default", () => {
  // Instance Config: project unset AND global unset → the inherit option still
  // shows, falling back to the code default (labelled 'using code default').
  renderField({
    eff: {
      "embedding.provider": { value: "openai", source: "default", inherited: null },
    },
    localSource: "project",
    inheritFrom: "global",
    raw: undefined,
  });
  const inherit = screen.getByTestId("field-inherit-embedding.provider");
  expect(inherit).toHaveTextContent(/using code default: openai/i);
  // It is the selected option while inheriting.
  expect(inherit).toHaveAttribute("aria-checked", "true");
});

test("no parent value at all (no global, no code default) → no inherit option", () => {
  // e.g. an api_key_env field: nothing to inherit, so just the input shows.
  renderField({
    field: {
      key: "api_key_env",
      dotpath: "embedding.api_key_env",
      label: "API key env var",
      widget: "text",
    },
    eff: {
      "embedding.api_key_env": { value: null, source: "unset", inherited: null },
    },
    localSource: "project",
    inheritFrom: "global",
    raw: undefined,
  });
  expect(
    screen.queryByTestId("field-inherit-embedding.api_key_env"),
  ).toBeNull();
});

test("there is no Override button anymore", () => {
  renderField({
    eff: {
      "embedding.provider": { value: "cohere", source: "global", inherited: null },
    },
    raw: undefined,
  });
  expect(
    screen.queryByTestId("field-override-embedding.provider"),
  ).toBeNull();
  expect(screen.queryByTestId("field-unset-embedding.provider")).toBeNull();
});

test("readonly field renders disabled value + managed-by-init note, no editing", () => {
  const setValue = vi.fn();
  const roField: SchemaField = {
    key: "state_dir",
    dotpath: "project.state_dir",
    label: "State dir",
    widget: "text",
    readonly: true,
  };
  render(
    <Field
      field={roField}
      getValue={() => "/home/u/proj/.brainpalace"}
      setValue={setValue}
      onInherit={() => {}}
      effective={{
        "project.state_dir": {
          value: "/home/u/proj/.brainpalace",
          source: "project",
          inherited: null,
        },
      }}
    />,
  );
  const ro = screen.getByTestId("field-readonly-project.state_dir");
  expect(ro).toHaveTextContent("/home/u/proj/.brainpalace");
  expect(ro).toHaveTextContent(/managed by init/i);
  expect(screen.queryByTestId("field-inherit-project.state_dir")).toBeNull();
  expect(setValue).not.toHaveBeenCalled();
});
