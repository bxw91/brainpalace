import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient } from "@tanstack/react-query";
import { useLiveInstances } from "./useLiveInstances";

// Minimal EventSource stub we can drive from the test.
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  readyState = 0;
  onerror: ((e: unknown) => void) | null = null;
  listeners = new Map<string, ((e: MessageEvent) => void)[]>();
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, cb: (e: MessageEvent) => void) {
    const arr = this.listeners.get(type) ?? [];
    arr.push(cb);
    this.listeners.set(type, arr);
  }
  removeEventListener(type: string, cb: (e: MessageEvent) => void) {
    const arr = (this.listeners.get(type) ?? []).filter((x) => x !== cb);
    this.listeners.set(type, arr);
  }
  emit(type: string, data: string) {
    (this.listeners.get(type) ?? []).forEach((cb) =>
      cb({ data } as MessageEvent),
    );
  }
  fail() {
    this.onerror?.(new Event("error"));
  }
  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useLiveInstances", () => {
  it("feeds SSE instances payloads into the query cache", async () => {
    const qc = new QueryClient();
    renderHook(() => useLiveInstances(qc));
    const es = FakeEventSource.instances[0];
    expect(es.url).toContain("/dashboard/api/events");

    act(() => {
      es.emit(
        "instances",
        JSON.stringify([
          {
            id: "a",
            name: "alpha",
            status: "running",
            project_root: "/p/a",
            base_url: "http://x",
            mode: "project",
          },
        ]),
      );
    });

    await waitFor(() => {
      const cached = qc.getQueryData(["instances"]) as { id: string }[] | undefined;
      expect(cached?.[0]?.id).toBe("a");
    });
  });

  it("falls back to polling on SSE error", async () => {
    const qc = new QueryClient();
    const { result } = renderHook(() => useLiveInstances(qc));
    expect(result.current.fallback).toBe(false);
    const es = FakeEventSource.instances[0];

    act(() => es.fail());

    await waitFor(() => expect(result.current.fallback).toBe(true));
  });

  it("closes the stream on unmount", () => {
    const qc = new QueryClient();
    const { unmount } = renderHook(() => useLiveInstances(qc));
    const es = FakeEventSource.instances[0];
    unmount();
    expect(es.closed).toBe(true);
  });
});
