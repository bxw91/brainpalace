import { describe, it, expect } from "vitest";
import {
  formatDate,
  formatTime,
  formatDateTime,
  formatShortDate,
  formatHour,
} from "./datetime";

// Fixed local-time instant: 2026-01-09 14:05:07 (afternoon, single-digit day).
const d = new Date(2026, 0, 9, 14, 5, 7);
// Morning instant for AM/12h edge: 2026-12-31 00:30:00.
const midnight = new Date(2026, 11, 31, 0, 30, 0);

describe("formatDate", () => {
  it("dd.mm.yyyy is zero-padded day.month.year", () => {
    expect(formatDate(d, "dd.mm.yyyy")).toBe("09.01.2026");
  });
  it("mm.dd.yyyy swaps day/month", () => {
    expect(formatDate(d, "mm.dd.yyyy")).toBe("01.09.2026");
  });
  it("yyyy-mm-dd is ISO order", () => {
    expect(formatDate(d, "yyyy-mm-dd")).toBe("2026-01-09");
  });
});

describe("formatTime", () => {
  it("24h is zero-padded with seconds", () => {
    expect(formatTime(d, "24h")).toBe("14:05:07");
  });
  it("12h converts the hour and appends a meridiem", () => {
    expect(formatTime(d, "12h")).toBe("2:05:07 PM");
  });
  it("12h renders midnight as 12 AM", () => {
    expect(formatTime(midnight, "12h")).toBe("12:30:00 AM");
  });
  it("drops seconds when asked", () => {
    expect(formatTime(d, "24h", false)).toBe("14:05");
  });
});

describe("formatDateTime", () => {
  it("joins date and time per both prefs", () => {
    expect(formatDateTime(d, "dd.mm.yyyy", "24h")).toBe("09.01.2026 14:05:07");
  });
});

describe("compact chart helpers", () => {
  it("formatShortDate drops the year, keeps field order", () => {
    expect(formatShortDate(d, "dd.mm.yyyy")).toBe("09.01");
    expect(formatShortDate(d, "mm.dd.yyyy")).toBe("01.09");
    expect(formatShortDate(d, "yyyy-mm-dd")).toBe("01-09");
  });
  it("formatHour renders an hour bucket per clock format", () => {
    expect(formatHour(d, "24h")).toBe("14:00");
    expect(formatHour(d, "12h")).toBe("2PM");
    expect(formatHour(midnight, "12h")).toBe("12AM");
  });
});
