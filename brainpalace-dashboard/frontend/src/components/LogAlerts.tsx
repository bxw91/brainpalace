export type LogAlert = { kind: "error" | "self-heal" | "auth"; line: string };

const MATCHERS: Array<[LogAlert["kind"], RegExp]> = [
  ["error", /\b(ERROR|CRITICAL|Traceback)\b/],
  ["self-heal", /self-heal|crash-loop/i],
  ["auth", /Unauthorized|401|invalid token/i],
];

/** Classify log lines into alert-worthy events; first matching kind wins. */
export function extractAlerts(lines: string[]): LogAlert[] {
  const alerts: LogAlert[] = [];
  for (const line of lines) {
    const hit = MATCHERS.find(([, re]) => re.test(line));
    if (hit) alerts.push({ kind: hit[0], line });
  }
  return alerts;
}

const KIND_TONE: Record<LogAlert["kind"], string> = {
  error: "bg-bad/15 text-bad",
  "self-heal": "bg-warn/15 text-warn",
  auth: "bg-warn/15 text-warn",
};

/** Alert strip above the raw log tail: counts per kind + the last 5 lines. */
export function LogAlerts({ lines }: { lines: string[] }) {
  const alerts = extractAlerts(lines);
  if (alerts.length === 0) return null;
  const counts = alerts.reduce<Record<string, number>>((acc, a) => {
    acc[a.kind] = (acc[a.kind] ?? 0) + 1;
    return acc;
  }, {});
  return (
    <div
      data-testid="log-alerts"
      className="panel flex flex-col gap-2 border-warn/30 p-4"
    >
      <p className="flex flex-wrap items-center gap-2">
        <span className="eyebrow">Alerts in view</span>
        {Object.entries(counts).map(([kind, n]) => (
          <span
            key={kind}
            className={`rounded px-1.5 py-0.5 text-[0.65rem] ${KIND_TONE[kind as LogAlert["kind"]]}`}
          >
            {n} {kind}
            {n === 1 ? "" : "s"}
          </span>
        ))}
      </p>
      <ul className="flex flex-col gap-1">
        {alerts.slice(-5).map((a, i) => (
          <li
            key={i}
            className="truncate font-mono text-xs text-fg-muted"
            title={a.line}
          >
            {a.line}
          </li>
        ))}
      </ul>
    </div>
  );
}
