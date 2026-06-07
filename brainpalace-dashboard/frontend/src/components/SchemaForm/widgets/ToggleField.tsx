export function ToggleField({
  dotpath,
  value,
  onChange,
  label,
}: {
  dotpath: string;
  value: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <button
        type="button"
        role="switch"
        aria-checked={value}
        aria-label={label}
        data-testid={`toggle-${dotpath}`}
        onClick={() => onChange(!value)}
        className={[
          "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors duration-200",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
          value
            ? "border-accent/50 bg-accent/80"
            : "border-line-strong bg-ink-600",
        ].join(" ")}
      >
        <span
          aria-hidden="true"
          className={[
            "inline-block h-4 w-4 transform rounded-full bg-fg shadow transition-transform duration-200",
            value ? "translate-x-6" : "translate-x-1",
          ].join(" ")}
        />
      </button>
      {/* High-contrast state text (#9) — the bare switch was hard to read. */}
      <span
        id={`span-toggle-state-${dotpath}`}
        data-testid={`toggle-state-${dotpath}`}
        aria-hidden="true"
        className={[
          "select-none text-xs font-medium",
          value ? "text-accent" : "text-fg-faint",
        ].join(" ")}
      >
        {value ? "Enabled" : "Disabled"}
      </span>
    </span>
  );
}
