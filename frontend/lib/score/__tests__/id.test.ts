import { generateId } from "../id";

describe("generateId", () => {
  it("should prefix the generated id with the given prefix", () => {
    const id = generateId("note");

    expect(id).toMatch(/^note-/);
  });

  it("should return a different id on each call", () => {
    const first = generateId("hit");
    const second = generateId("hit");

    expect(first).not.toBe(second);
  });
});
