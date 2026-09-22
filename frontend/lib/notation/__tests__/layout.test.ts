import { computeRowLayout } from "../layout";

describe("computeRowLayout", () => {
  it("should place all measures in a single row when they fit within the available width", () => {
    const placed = computeRowLayout([80, 80, 80], 1000);

    expect(placed.map((p) => p.row)).toEqual([0, 0, 0]);
    expect(placed.map((p) => p.col)).toEqual([0, 1, 2]);
  });

  it("should give a measure with a larger minWidth a proportionally wider column than a sparser neighbor", () => {
    const [sparse, dense] = computeRowLayout([50, 300], 1000, { minMeasureWidth: 0, clefWidth: 0, timeSignatureWidth: 0 });

    expect(dense.width).toBeGreaterThan(sparse.width);
    expect(dense.width).toBe(300);
    expect(sparse.width).toBe(50);
  });

  it("should floor a very sparse measure's width at the configured minimum", () => {
    const [placed] = computeRowLayout([10], 1000, { minMeasureWidth: 120, clefWidth: 0, timeSignatureWidth: 0 });

    expect(placed.width).toBe(120);
  });

  it("should wrap to a new row when the next measure would exceed the available width", () => {
    const placed = computeRowLayout([100, 100, 100], 250, {
      minMeasureWidth: 0,
      clefWidth: 0,
      timeSignatureWidth: 0,
      startX: 0,
    });

    expect(placed.map((p) => p.row)).toEqual([0, 0, 1]);
    expect(placed.map((p) => p.col)).toEqual([0, 1, 0]);
  });

  it("should still place a single measure wider than the available width, on its own row, instead of looping forever", () => {
    const placed = computeRowLayout([500], 100, { minMeasureWidth: 0, clefWidth: 0, timeSignatureWidth: 0 });

    expect(placed).toHaveLength(1);
    expect(placed[0].row).toBe(0);
    expect(placed[0].width).toBe(500);
  });

  it("should reserve extra width for the clef on the first measure of every row, not later measures in the same row", () => {
    const placed = computeRowLayout([100, 100, 100], 250, {
      minMeasureWidth: 0,
      clefWidth: 40,
      timeSignatureWidth: 0,
      startX: 0,
    });

    // measure 0 (row 0, col 0) and measure 2 (row 1, col 0) are each first-in-row.
    expect(placed[0].width).toBe(140);
    expect(placed[2].width).toBe(140);
    // measure 1 (row 0, col 1) is not first-in-row.
    expect(placed[1].width).toBe(100);
  });

  it("should reserve extra width for the time signature only on the very first measure overall", () => {
    const placed = computeRowLayout([100, 100], 1000, {
      minMeasureWidth: 0,
      clefWidth: 40,
      timeSignatureWidth: 30,
      startX: 0,
    });

    // measure 0: clef + time signature. measure 1: neither (same row, not first).
    expect(placed[0].width).toBe(170);
    expect(placed[1].width).toBe(100);
  });

  it("should position x values contiguously within a row, starting at startX", () => {
    const placed = computeRowLayout([100, 100], 1000, {
      minMeasureWidth: 0,
      clefWidth: 0,
      timeSignatureWidth: 0,
      startX: 10,
    });

    expect(placed[0].x).toBe(10);
    expect(placed[1].x).toBe(110);
  });

  it("should preserve the original measure index for each placed entry", () => {
    const placed = computeRowLayout([100, 100, 100], 150, {
      minMeasureWidth: 0,
      clefWidth: 0,
      timeSignatureWidth: 0,
      startX: 0,
    });

    expect(placed.map((p) => p.index)).toEqual([0, 1, 2]);
  });

  it("should return an empty array for no measures", () => {
    expect(computeRowLayout([], 1000)).toEqual([]);
  });
});
