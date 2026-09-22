import "@testing-library/jest-dom";

if (typeof global.structuredClone !== "function") {
  global.structuredClone = (value: unknown) => JSON.parse(JSON.stringify(value));
}

// jsdom does not implement ResizeObserver. This no-op default lets any
// component construct one without crashing; tests that need to drive actual
// resize behavior install their own controllable mock instead.
if (typeof global.ResizeObserver === "undefined") {
  class NoopResizeObserver implements ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  global.ResizeObserver = NoopResizeObserver;
}
