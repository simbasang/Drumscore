import {
  beatPeriodAt,
  beatsInWindow,
  contextTimeForSourceTime,
  countInClickTimes,
} from "../metronomeScheduling";
import type { Beat } from "@/lib/api/types";

function beat(source_time: number, measure: number, beatNumber: number, isDownbeat: boolean): Beat {
  return { source_time, measure, beat: beatNumber, is_downbeat: isDownbeat, confidence: null };
}

const BEATS: Beat[] = [
  beat(0, 1, 1, true),
  beat(0.5, 1, 2, false),
  beat(1.0, 1, 3, false),
  beat(1.5, 1, 4, false),
  beat(2.0, 2, 1, true),
];

describe("beatPeriodAt", () => {
  it("should return null when fewer than two beats are available", () => {
    expect(beatPeriodAt([beat(0, 1, 1, true)], 0)).toBeNull();
  });

  it("should return the interval to the next beat when sourceTime lands on a beat with a successor", () => {
    expect(beatPeriodAt(BEATS, 0.5)).toBe(0.5);
  });

  it("should return the interval from the previous beat when sourceTime is at or past the last beat", () => {
    expect(beatPeriodAt(BEATS, 5)).toBe(0.5);
  });

  it("should use the nearest preceding beat's period for a time between two anchors", () => {
    expect(beatPeriodAt(BEATS, 0.75)).toBe(0.5);
  });
});

describe("beatsInWindow", () => {
  it("should return only beats within [windowStart, windowEnd)", () => {
    const result = beatsInWindow(BEATS, 0.5, 1.5);

    expect(result.map((b) => b.source_time)).toEqual([0.5, 1.0]);
  });

  it("should return an empty array when no beats fall in the window", () => {
    expect(beatsInWindow(BEATS, 10, 20)).toEqual([]);
  });
});

describe("countInClickTimes", () => {
  it("should return an empty array when fewer than two beats are available", () => {
    expect(countInClickTimes([beat(0, 1, 1, true)], 0, 4)).toEqual([]);
  });

  it("should space clicks by the local beat period starting at 0", () => {
    const times = countInClickTimes(BEATS, 0, 4);

    expect(times).toEqual([0, 0.5, 1.0, 1.5]);
  });
});

describe("contextTimeForSourceTime", () => {
  it("should return the current context time unchanged for the current source time", () => {
    expect(contextTimeForSourceTime(5, 5, 100, 1)).toBe(100);
  });

  it("should convert a future source time to a real-time deadline at rate 1", () => {
    expect(contextTimeForSourceTime(7, 5, 100, 1)).toBe(102);
  });

  it("should divide by rate so a faster rate reaches the same source time sooner in real time", () => {
    expect(contextTimeForSourceTime(7, 5, 100, 2)).toBe(101);
  });
});
