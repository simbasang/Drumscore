import {
  computeAutoScrollLeft,
  computeSlotTimeSeconds,
  interpolatePlayheadX,
  type TimelinePoint,
} from "../timeline";

describe("computeSlotTimeSeconds", () => {
  it.each([
    [1, 1, 0, 0.0],
    [1, 1, 1, 0.125],
    [1, 2, 0, 0.5],
    [1, 4, 0, 1.5],
    [2, 1, 0, 2.0],
    [2, 1, 1, 2.125],
  ])("measure %i beat %i subdivision %i at 120bpm -> %fs", (measure, beat, subdivision, expected) => {
    expect(computeSlotTimeSeconds(measure, beat, subdivision, 120)).toBeCloseTo(expected, 6);
  });
});

describe("interpolatePlayheadX", () => {
  const points: TimelinePoint[] = [
    { time: 0, x: 10, row: 0 },
    { time: 1, x: 110, row: 0 },
    { time: 2, x: 210, row: 0 },
  ];

  it("should return null for an empty timeline", () => {
    expect(interpolatePlayheadX([], 1)).toBeNull();
  });

  it("should clamp to the first point before the timeline starts", () => {
    expect(interpolatePlayheadX(points, -5)).toEqual(points[0]);
  });

  it("should clamp to the last point after the timeline ends", () => {
    expect(interpolatePlayheadX(points, 100)).toEqual(points[2]);
  });

  it("should return the exact point when time matches exactly", () => {
    const result = interpolatePlayheadX(points, 1);
    expect(result?.x).toBe(110);
  });

  it("should linearly interpolate x between two bracketing points", () => {
    const result = interpolatePlayheadX(points, 0.5);
    expect(result?.x).toBe(60);
  });

  it("should hold at the old row's last point instead of sliding backward into the next row's x", () => {
    const rowChangePoints: TimelinePoint[] = [
      { time: 0, x: 190, row: 0 },
      { time: 1, x: 10, row: 1 },
    ];
    const result = interpolatePlayheadX(rowChangePoints, 0.5);
    expect(result).toEqual({ time: 0.5, x: 190, row: 0 });
  });

  it("should cut directly to the new row's first point once its time is reached", () => {
    const rowChangePoints: TimelinePoint[] = [
      { time: 0, x: 190, row: 0 },
      { time: 1, x: 10, row: 1 },
    ];
    const result = interpolatePlayheadX(rowChangePoints, 1);
    expect(result).toEqual({ time: 1, x: 10, row: 1 });
  });

  it("should never report a smaller x while still on the same row across a row-boundary bracket", () => {
    const rowChangePoints: TimelinePoint[] = [
      { time: 0, x: 190, row: 0 },
      { time: 1, x: 10, row: 1 },
    ];
    const beforeBoundary = interpolatePlayheadX(rowChangePoints, 0.9)!;
    const atBoundary = interpolatePlayheadX(rowChangePoints, 1)!;

    expect(beforeBoundary.row).toBe(0);
    expect(beforeBoundary.x).toBe(190);
    expect(atBoundary.row).toBe(1);
  });

  it("should still interpolate x smoothly between two points on the same row", () => {
    const sameRowPoints: TimelinePoint[] = [
      { time: 0, x: 10, row: 2 },
      { time: 1, x: 210, row: 2 },
    ];
    const result = interpolatePlayheadX(sameRowPoints, 0.5);
    expect(result).toEqual({ time: 0.5, x: 110, row: 2 });
  });
});

describe("computeAutoScrollLeft", () => {
  it("should leave scrollLeft unchanged when the target is already comfortably visible", () => {
    expect(computeAutoScrollLeft(0, 400, 100)).toBe(0);
  });

  it("should scroll left when the target is near or past the left edge", () => {
    expect(computeAutoScrollLeft(0, 400, 20)).toBe(0);
    expect(computeAutoScrollLeft(200, 400, 210)).toBe(170);
  });

  it("should never scroll to a negative position", () => {
    expect(computeAutoScrollLeft(0, 400, 5)).toBe(0);
  });

  it("should scroll right when the target is near or past the right edge", () => {
    expect(computeAutoScrollLeft(0, 400, 500)).toBe(140);
  });

  it("should account for the current scroll position, not just the raw viewport", () => {
    expect(computeAutoScrollLeft(300, 400, 750)).toBe(390);
  });
});
