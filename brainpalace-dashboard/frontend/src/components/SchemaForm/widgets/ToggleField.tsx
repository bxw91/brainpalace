export function ToggleField({
  dotpath,
  value,
  onChange,
  label,
  inherited = false,
}: {
  dotpath: string;
  value: boolean;
  onChange: (v: boolean) => void;
  label: string;
  /**
   * The value is NOT set in the project config — it reflects an inherited
   * global / code-default. Renders muted (greyed track + faint label) so an
   * inherited "on"/"off" doesn't masquerade as a deliberate local choice
   * (#8/#11). Still clickable: flipping promotes the key to a local override.
   */
  inherited?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <button
        type="button"
        role="switch"
        aria-checked={value}
        aria-label={label}
        data-testid={`toggle-${dotpath}`}
        data-inherited={inherited ? "true" : undefined}
        onClick={() => onChange(!value)}
        className={[
          "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors duration-200",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
          inherited
            ? "border-line-strong bg-ink-500 opacity-60"
            : value
              ? "border-accent/50 bg-accent/80"
              : "border-line-strong bg-ink-600",
        ].join(" ")}
      >
        <span
          aria-hidden="true"
          className={[
            "inline-block h-4 w-4 transform rounded-full shadow transition-transform duration-200",
            inherited ? "bg-fg-faint" : "bg-fg",
            value ? "translate-x-6" : "translate-x-1",
          ].join(" ")}
        />
      </button>
      {/* High-contrast state text (#9) — the bare switch was hard to read.
          Inherited values stay faint regardless of on/off (#8/#11). */}
      <span
        id={`span-toggle-state-${dotpath}`}
        data-testid={`toggle-state-${dotpath}`}
        aria-hidden="true"
        className={[
          "select-none text-xs font-medium",
          inherited
            ? "text-fg-faint"
            : value
              ? "text-accent"
              : "text-fg-faint",
        ].join(" ")}
      >
        {inherited
          ? value
            ? "Enabled · inherited"
            : "Disabled · inherited"
          : value
            ? "Enabled"
            : "Disabled"}
      </span>
    </span>
  );
}
