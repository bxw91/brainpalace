/**
 * Display date/time formatting honouring the dashboard's `time_format` /
 * `date_format` preferences (the `dashboard:` block of the XDG config.yaml,
 * editable on the Settings tab). Defaults: 24-hour clock, `dd.mm.yyyy` dates.
 *
 * Use `useDisplayFormat()` inside components; the pure `formatX` helpers exist
 * for tests and module-level callers that already hold the preference values.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  getSettings,
  type DateFormat,
  type TimeFormat,
} from "../api/client";

const pad = (n: number) => String(n).padStart(2, "0");

export const DEFAULT_DATE_FORMAT: DateFormat = "dd.mm.yyyy";
export const DEFAULT_TIME_FORMAT: TimeFormat = "24h";

export function formatDate(d: Date, fmt: DateFormat): string {
  const y = d.getFullYear();
  const m = pad(d.getMonth() + 1);
  const day = pad(d.getDate());
  switch (fmt) {
    case "mm.dd.yyyy":
      return `${m}.${day}.${y}`;
    case "yyyy-mm-dd":
      return `${y}-${m}-${day}`;
    default:
      return `${day}.${m}.${y}`;
  }
}

export function formatTime(d: Date, fmt: TimeFormat, withSeconds = true): string {
  const h24 = d.getHours();
  const mm = pad(d.getMinutes());
  const tail = withSeconds ? `:${pad(d.getSeconds())}` : "";
  if (fmt === "12h") {
    const ampm = h24 < 12 ? "AM" : "PM";
    const h12 = h24 % 12 === 0 ? 12 : h24 % 12;
    return `${h12}:${mm}${tail} ${ampm}`;
  }
  return `${pad(h24)}:${mm}${tail}`;
}

export function formatDateTime(
  d: Date,
  dateFmt: DateFormat,
  timeFmt: TimeFormat,
): string {
  return `${formatDate(d, dateFmt)} ${formatTime(d, timeFmt)}`;
}

/** Compact day/month label for chart ticks (no year), honouring field order. */
export function formatShortDate(d: Date, fmt: DateFormat): string {
  const m = pad(d.getMonth() + 1);
  const day = pad(d.getDate());
  switch (fmt) {
    case "mm.dd.yyyy":
      return `${m}.${day}`;
    case "yyyy-mm-dd":
      return `${m}-${day}`;
    default:
      return `${day}.${m}`;
  }
}

/** Hour-of-day label for compact chart ticks (no minutes/seconds). */
export function formatHour(d: Date, fmt: TimeFormat): string {
  const h24 = d.getHours();
  if (fmt === "12h") {
    const ampm = h24 < 12 ? "AM" : "PM";
    const h12 = h24 % 12 === 0 ? 12 : h24 % 12;
    return `${h12}${ampm}`;
  }
  return `${pad(h24)}:00`;
}

export type DisplayFormat = {
  dateFormat: DateFormat;
  timeFormat: TimeFormat;
  formatDate: (d: Date) => string;
  formatTime: (d: Date, withSeconds?: boolean) => string;
  formatDateTime: (d: Date) => string;
  formatShortDate: (d: Date) => string;
  formatHour: (d: Date) => string;
};

/**
 * Resolve the live display-format preferences (shares the `["settings"]`
 * react-query cache with the Settings tab) and return bound formatters.
 */
export function useDisplayFormat(): DisplayFormat {
  const { data } = useQuery({
    queryKey: ["settings"],
    queryFn: getSettings,
    staleTime: 60_000,
  });
  const dateFormat = data?.date_format ?? DEFAULT_DATE_FORMAT;
  const timeFormat = data?.time_format ?? DEFAULT_TIME_FORMAT;
  return useMemo(
    () => ({
      dateFormat,
      timeFormat,
      formatDate: (d: Date) => formatDate(d, dateFormat),
      formatTime: (d: Date, withSeconds = true) =>
        formatTime(d, timeFormat, withSeconds),
      formatDateTime: (d: Date) => formatDateTime(d, dateFormat, timeFormat),
      formatShortDate: (d: Date) => formatShortDate(d, dateFormat),
      formatHour: (d: Date) => formatHour(d, timeFormat),
    }),
    [dateFormat, timeFormat],
  );
}
