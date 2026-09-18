import type { AnalysisEvent } from "@/lib/api/jobs";
import { buildMeasures, type MeasureSpec } from "../buildScore";

function event(overrides: Partial<AnalysisEvent>): AnalysisEvent {
  return {
    id: "e",
    time: 0,
    instrument: "kick",
    measure: 1,
    beat: 1,
    subdivision: 0,
    ...overrides,
  };
}

const DURATION_SIXTEENTHS: Record<string, number> = { "1": 16, "2": 8, "4": 4, "8": 2, "16": 1 };

function totalSixteenths(measure: MeasureSpec): number {
  return measure.reduce((sum, slot) => sum + DURATION_SIXTEENTHS[slot.duration], 0);
}

describe("buildMeasures", () => {
  it("should return an empty array for no events", () => {
    expect(buildMeasures([])).toEqual([]);
  });

  it("should consolidate an entirely empty measure into a single whole rest", () => {
    const measures = buildMeasures([event({ instrument: "kick", measure: 2, beat: 1, subdivision: 0 })]);

    expect(measures[0]).toEqual([{ type: "rest", duration: "1", startSixteenth: 0 }]);
  });

  it("should place a single event in its slot and consolidate the remaining rests down to the fewest tied durations", () => {
    const measures = buildMeasures([event({ instrument: "kick", beat: 1, subdivision: 0 })]);

    expect(measures).toHaveLength(1);
    expect(measures[0]).toEqual([
      { type: "note", keys: ["f/4"], articulations: [], duration: "16", startSixteenth: 0 },
      { type: "rest", duration: "16", startSixteenth: 1 },
      { type: "rest", duration: "8", startSixteenth: 2 },
      { type: "rest", duration: "4", startSixteenth: 4 },
      { type: "rest", duration: "2", startSixteenth: 8 },
    ]);
  });

  it("should combine simultaneous instruments into a single note with multiple keys", () => {
    const measures = buildMeasures([
      event({ instrument: "kick", beat: 1, subdivision: 0 }),
      event({ instrument: "hihat_closed", beat: 1, subdivision: 0 }),
    ]);

    expect(measures[0][0]).toEqual({
      type: "note",
      keys: ["f/4", "g/5/x2"],
      articulations: [],
      duration: "16",
      startSixteenth: 0,
    });
  });

  it("should include the open-hihat articulation for hihat_open events", () => {
    const measures = buildMeasures([event({ instrument: "hihat_open", beat: 1, subdivision: 0 })]);

    expect(measures[0][0]).toEqual({
      type: "note",
      keys: ["g/5/x2"],
      articulations: ["ah"],
      duration: "16",
      startSixteenth: 0,
    });
  });

  it("should deduplicate identical instruments in the same slot", () => {
    const measures = buildMeasures([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0 }),
      event({ id: "b", instrument: "kick", beat: 1, subdivision: 0 }),
    ]);

    expect(measures[0][0].type).toBe("note");
    expect((measures[0][0] as { keys: string[] }).keys).toEqual(["f/4"]);
  });

  it("should keep a note at its correct metric position even after leading/trailing rests are consolidated", () => {
    const measures = buildMeasures([event({ instrument: "snare", beat: 2, subdivision: 1 })]);

    const noteSlot = measures[0].find((slot) => slot.type === "note");
    expect(noteSlot).toEqual({
      type: "note",
      keys: ["c/5"],
      articulations: [],
      duration: "16",
      // beat 2, subdivision 1 -> sixteenth position (2-1)*4 + 1 = 5
      startSixteenth: 5,
    });
  });

  it("should always account for exactly one measure's worth of duration, regardless of note placement", () => {
    const placements = [
      [{ beat: 1, subdivision: 0 }],
      [{ beat: 1, subdivision: 0 }, { beat: 3, subdivision: 0 }],
      [{ beat: 1, subdivision: 0 }, { beat: 2, subdivision: 0 }, { beat: 4, subdivision: 3 }],
    ];

    for (const placement of placements) {
      const measures = buildMeasures(
        placement.map((p, i) => event({ id: `e${i}`, instrument: "kick", ...p })),
      );

      expect(totalSixteenths(measures[0])).toBe(16);
    }
  });

  it("should produce one measure per distinct measure number, filling any gaps", () => {
    const measures = buildMeasures([event({ instrument: "kick", measure: 2, beat: 1, subdivision: 0 })]);

    expect(measures).toHaveLength(2);
    expect(measures[0]).toEqual([{ type: "rest", duration: "1", startSixteenth: 0 }]);
    expect(measures[1][0].type).toBe("note");
  });

  it("should ignore events missing measure, beat, or subdivision", () => {
    const measures = buildMeasures([event({ instrument: "kick", measure: null })]);

    expect(measures).toEqual([]);
  });
});
