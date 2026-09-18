import { computeSlotTimeSeconds, interpolatePlayheadX, type TimelinePoint } from "../timeline";

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

  it("should use the left point's row for interpolated positions", () => {
    const rowChangePoints: TimelinePoint[] = [
      { time: 0, x: 190, row: 0 },
      { time: 1, x: 10, row: 1 },
    ];
    const result = interpolatePlayheadX(rowChangePoints, 0.5);
    expect(result?.row).toBe(0);
  });
});
