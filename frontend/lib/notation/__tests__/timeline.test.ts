import { computeAutoScrollLeft, interpolatePlayheadX, type TimelinePoint } from "../timeline";

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

  it("should hold instead of sliding backward when a dense measure's notes overflow into the next measure's column on the same row", () => {
    // A dense 16th-note measure can overflow VexFlow's allocated column
    // width, so the next measure's first note can render to the LEFT of
    // the previous measure's last note, even though both are on the same
    // row and time only moves forward.
    const overflowPoints: TimelinePoint[] = [
      { time: 0, x: 75, row: 0 },
      { time: 1, x: 455, row: 0 },
      { time: 1.1, x: 226, row: 0 },
    ];
    const result = interpolatePlayheadX(overflowPoints, 1.05);
    expect(result).toEqual({ time: 1.05, x: 455, row: 0 });
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
