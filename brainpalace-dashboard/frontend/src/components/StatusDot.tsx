import type { InstanceStatus } from "../api/types";

const DOT: Record<InstanceStatus, string> = {
  running: "bg-run shadow-[0_0_0_3px_rgba(52,211,153,0.15)]",
  unhealthy: "bg-warn shadow-[0_0_0_3px_rgba(251,191,36,0.15)]",
  stopped: "bg-idle",
  stale: "bg-bad shadow-[0_0_0_3px_rgba(251,113,133,0.15)]",
};

export const STATUS_LABEL: Record<InstanceStatus, string> = {
  running: "Running",
  unhealthy: "Unhealthy",
  stopped: "Stopped",
  stale: "Stale",
};

/** Small semantic status indicator. Pulses while running. */
export function StatusDot({
  id,
  status,
  className = "",
}: {
  id: string;
  status: InstanceStatus;
  className?: string;
}) {
  const pulse = status === "running" ? "animate-pulse-dot" : "";
  return (
    <span
      id={`span-status-${id}`}
      data-testid={`status-${id}`}
      data-status={status}
      role="img"
      title={STATUS_LABEL[status]}
      aria-label={STATUS_LABEL[status]}
      className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${DOT[status]} ${pulse} ${className}`}
    />
  );
}
