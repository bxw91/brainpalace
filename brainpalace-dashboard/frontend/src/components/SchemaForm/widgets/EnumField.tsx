export function EnumField({
  dotpath,
  options,
  value,
  defaultValue,
  onChange,
}: {
  dotpath: string;
  options: string[];
  value: string | undefined;
  defaultValue?: string;
  onChange: (v: string) => void;
}) {
  return (
    <div
      role="group"
      data-testid={`enum-${dotpath}`}
      className="inline-flex flex-wrap gap-1 rounded-lg border border-line bg-ink-900/50 p-1"
    >
      {options.map((opt) => {
        const active = opt === value;
        // When nothing is set, ring the effective default so users can see which
        // option is active by default (e.g. storage backend = chroma).
        const isDefault = value === undefined && opt === defaultValue;
        return (
          <button
            key={opt}
            type="button"
            aria-pressed={active}
            data-selected={active ? "true" : "false"}
            data-testid={`enum-${dotpath}-${opt}`}
            onClick={() => onChange(opt)}
            className={[
              "rounded-md px-3 py-1.5 text-sm font-medium transition-all duration-150",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
              active
                ? "bg-accent text-ink-900 shadow-sm"
                : isDefault
                  ? "text-fg ring-1 ring-inset ring-accent/40"
                  : "text-fg-muted hover:bg-ink-700/60 hover:text-fg",
            ].join(" ")}
          >
            {opt}
            {isDefault && (
              <span className="ml-1.5 text-[0.62rem] uppercase tracking-wide text-accent/70">
                default
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
