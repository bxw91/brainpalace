import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { LogAlerts, extractAlerts } from "./LogAlerts";

const lines = [
  "2026-06-10 09:00:01 INFO uvicorn started",
  "2026-06-10 09:00:05 ERROR query failed: boom",
  "2026-06-10 09:01:00 WARNING self-heal: restarted file watcher",
  "2026-06-10 09:02:00 INFO Unauthorized request rejected",
  "2026-06-10 09:03:00 INFO all good",
];

describe("extractAlerts", () => {
  it("classifies error / self-heal / auth lines and skips noise", () => {
    const alerts = extractAlerts(lines);
    expect(alerts.map((a) => a.kind)).toEqual(["error", "self-heal", "auth"]);
  });
});

describe("LogAlerts", () => {
  it("renders counts and the most recent alerts", () => {
    render(<LogAlerts lines={lines} />);
    expect(screen.getByTestId("log-alerts")).toHaveTextContent("1 error");
    expect(screen.getByText(/query failed: boom/)).toBeInTheDocument();
  });

  it("renders nothing when there are no alerts", () => {
    render(<LogAlerts lines={["INFO fine", "INFO also fine"]} />);
    expect(screen.queryByTestId("log-alerts")).toBeNull();
  });
});
