import "@testing-library/jest-dom";

if (typeof global.structuredClone !== "function") {
  global.structuredClone = (value: unknown) => JSON.parse(JSON.stringify(value));
}
