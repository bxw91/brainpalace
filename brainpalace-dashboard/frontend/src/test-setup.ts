import "@testing-library/jest-dom";

// jsdom lacks ResizeObserver, which Recharts' ResponsiveContainer relies on.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!("ResizeObserver" in globalThis)) {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver =
    ResizeObserverStub;
}
