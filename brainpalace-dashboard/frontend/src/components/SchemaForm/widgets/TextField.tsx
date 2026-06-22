import { useState } from "react";

export function TextField({
  dotpath,
  value,
  onChange,
  secret = false,
  hasValue = false,
  placeholder,
  presets,
}: {
  dotpath: string;
  value: string;
  onChange: (v: string) => void;
  secret?: boolean;
  /** Whether a (secret) value is actually set — controls the masking dots. */
  hasValue?: boolean;
  placeholder?: string;
  presets?: string[];
}) {
  const inputId = `input-${dotpath}`;

  // Preset mode: show segmented presets + a "Custom…" entry that reveals the
  // free-text input only when chosen (or when the value isn't a known preset).
  const hasPresets = !!presets && presets.length > 0;
  const valueIsPreset = hasPresets && presets!.includes(value);
  const [customOpen, setCustomOpen] = useState(
    hasPresets ? !valueIsPreset && value !== "" : false,
  );

  if (hasPresets) {
    const showCustom = customOpen || (!valueIsPreset && value !== "");
    return (
      <div className="flex flex-col gap-2">
        <div role="group" className="inline-flex flex-wrap items-center gap-2">
          {presets!.map((p) => {
            const active = !showCustom && p === value;
            return (
              <button
                key={p}
                type="button"
                aria-pressed={active}
                data-testid={`preset-${dotpath}-${p}`}
                onClick={() => {
                  setCustomOpen(false);
                  onChange(p);
                }}
                className={[
                  "rounded-md border px-3 py-1.5 text-sm font-medium transition-all duration-150",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
                  active
                    ? "border-accent bg-accent text-ink-900"
                    : "border-line bg-ink-900/40 text-fg-muted hover:border-accent/50 hover:bg-ink-700/60 hover:text-fg",
                ].join(" ")}
              >
                {p}
              </button>
            );
          })}
          <button
            type="button"
            aria-pressed={showCustom}
            data-testid={`preset-${dotpath}-custom`}
            onClick={() => {
              setCustomOpen(true);
              if (valueIsPreset) onChange("");
            }}
            className={[
              "rounded-md px-3 py-1.5 text-sm font-medium transition-all duration-150",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
              showCustom
                ? "bg-accent text-ink-900"
                : "text-fg-muted hover:bg-ink-700/60 hover:text-fg",
            ].join(" ")}
          >
            Custom…
          </button>
        </div>
        {showCustom && (
          <input
            id={inputId}
            data-testid={`text-${dotpath}`}
            type="text"
            value={value}
            placeholder={placeholder}
            onChange={(e) => onChange(e.target.value)}
            className="w-full max-w-md rounded-lg border border-line bg-ink-900/50 px-3 py-2 text-sm text-fg outline-none transition-colors placeholder:text-fg-faint focus:border-accent/50 focus:ring-2 focus:ring-accent/30"
          />
        )}
      </div>
    );
  }

  return (
    <input
      id={inputId}
      data-testid={`text-${dotpath}`}
      type={secret ? "password" : "text"}
      value={value}
      placeholder={
        // Masking dots ONLY when a secret is actually set; empty otherwise (#3).
        secret && hasValue ? placeholder ?? "••••••••" : placeholder
      }
      autoComplete={secret ? "off" : undefined}
      onChange={(e) => onChange(e.target.value)}
      className="w-full max-w-md rounded-lg border border-line bg-ink-900/50 px-3 py-2 text-sm text-fg outline-none transition-colors placeholder:text-fg-faint focus:border-accent/50 focus:ring-2 focus:ring-accent/30"
    />
  );
}
