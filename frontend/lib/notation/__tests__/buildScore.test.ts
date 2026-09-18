import type { AnalysisEvent } from "@/lib/api/jobs";
import { buildMeasures } from "../buildScore";

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

describe("buildMeasures", () => {
  it("should return an empty array for no events", () => {
    expect(buildMeasures([])).toEqual([]);
  });

  it("should place a single event in its slot and fill the rest of the measure with rests", () => {
    const measures = buildMeasures([event({ instrument: "kick", beat: 1, subdivision: 0 })]);

    expect(measures).toHaveLength(1);
    expect(measures[0]).toHaveLength(16);
    expect(measures[0][0]).toEqual({ type: "note", keys: ["f/4"], articulations: [], duration: "16" });
    for (let i = 1; i < 16; i++) {
      expect(measures[0][i]).toEqual({ type: "rest", duration: "16" });
    }
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
    });
  });

  it("should include the open-hihat articulation for hihat_open events", () => {
    const measures = buildMeasures([event({ instrument: "hihat_open", beat: 1, subdivision: 0 })]);

    expect(measures[0][0]).toEqual({
      type: "note",
      keys: ["g/5/x2"],
      articulations: ["ah"],
      duration: "16",
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

  it("should place events at the correct slot index within a measure", () => {
    const measures = buildMeasures([event({ instrument: "snare", beat: 2, subdivision: 1 })]);

    // beat 2, subdivision 1 -> slot index (2-1)*4 + 1 = 5
    expect(measures[0][5]).toEqual({
      type: "note",
      keys: ["c/5"],
      articulations: [],
      duration: "16",
    });
  });

  it("should produce one measure per distinct measure number, filling any gaps", () => {
    const measures = buildMeasures([event({ instrument: "kick", measure: 2, beat: 1, subdivision: 0 })]);

    expect(measures).toHaveLength(2);
    expect(measures[0].every((slot) => slot.type === "rest")).toBe(true);
    expect(measures[1][0].type).toBe("note");
  });

  it("should ignore events missing measure, beat, or subdivision", () => {
    const measures = buildMeasures([event({ instrument: "kick", measure: null })]);

    expect(measures).toEqual([]);
  });
});
