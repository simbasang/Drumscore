import { consolidateDurations, consolidateRests, expandMeasure, toPosition, toSixteenthIndex } from "../grid";
import type { Measure, ScoreNote } from "../types";

function note(measure: number, beat: number, subdivision: number): ScoreNote {
  return {
    type: "note",
    id: "n",
    position: { measure, beat, subdivision },
    duration: "16",
    hits: [
      {
        id: "h",
        sourceEventId: "e",
        time: 0,
        instrument: "kick",
        confidence: null,
        provenance: "drumscript",
      },
    ],
  };
}

function positionParts(sixteenthIndex: number): [beat: number, subdivision: number] {
  const position = toPosition(1, sixteenthIndex);
  return [position.beat, position.subdivision];
}

describe("toSixteenthIndex", () => {
  it("should convert beat 1 subdivision 0 to index 0", () => {
    const index = toSixteenthIndex({ measure: 1, beat: 1, subdivision: 0 });

    expect(index).toBe(0);
  });

  it("should convert beat 2 subdivision 1 to index 5", () => {
    const index = toSixteenthIndex({ measure: 1, beat: 2, subdivision: 1 });

    expect(index).toBe(5);
  });

  it("should convert beat 4 subdivision 3 to index 15", () => {
    const index = toSixteenthIndex({ measure: 1, beat: 4, subdivision: 3 });

    expect(index).toBe(15);
  });
});

describe("toPosition", () => {
  it("should round-trip through toSixteenthIndex for every index in a measure", () => {
    for (let index = 0; index < 16; index++) {
      const position = toPosition(3, index);

      expect(position.measure).toBe(3);
      expect(toSixteenthIndex(position)).toBe(index);
    }
  });
});

describe("consolidateRests", () => {
  it("should merge sixteen individual rests into a single whole rest", () => {
    const slots: Measure = Array.from({ length: 16 }, (_, i) => ({
      type: "rest" as const,
      id: `r${i}`,
      duration: "16",
      position: toPosition(1, i),
    }));

    const result = consolidateRests(slots);

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ type: "rest", duration: "1" });
  });

  it("should leave a note slot unchanged", () => {
    const slots: Measure = [note(1, 1, 0)];

    const result = consolidateRests(slots);

    expect(result).toEqual([note(1, 1, 0)]);
  });

  it("should merge the rests around an untouched note down to the fewest tied durations", () => {
    const slots: Measure = [
      note(1, 1, 0),
      ...Array.from({ length: 15 }, (_, i) => ({
        type: "rest" as const,
        id: `r${i}`,
        duration: "16",
        position: toPosition(1, i + 1),
      })),
    ];

    const result = consolidateRests(slots);

    expect(result.map((slot) => slot.duration)).toEqual(["16", "16", "8", "4", "2"]);
  });
});

describe("expandMeasure", () => {
  it("should return sixteen single-sixteenth rest slots for a measure with no notes", () => {
    const expanded = expandMeasure([], 2);

    expect(expanded).toHaveLength(16);
    expect(expanded.every((slot) => slot.type === "rest" && slot.duration === "16")).toBe(true);
    expect(expanded[0].position).toEqual({ measure: 2, beat: 1, subdivision: 0 });
  });

  it("should preserve an existing note at its own sixteenth index and fill the rest with single-sixteenth rests", () => {
    const measure: Measure = [note(4, 2, 1)];

    const expanded = expandMeasure(measure, 4);

    expect(expanded).toHaveLength(16);
    expect(expanded[5]).toMatchObject({ type: "note", position: { measure: 4, beat: 2, subdivision: 1 } });
    expect(expanded.filter((slot) => slot.type === "rest")).toHaveLength(15);
  });
});

describe("consolidateDurations", () => {
  it("should extend a single note in an otherwise-empty measure into a whole note", () => {
    const slots: Measure = [
      note(1, 1, 0),
      ...Array.from({ length: 15 }, (_, i) => ({
        type: "rest" as const,
        id: `r${i}`,
        duration: "16",
        position: toPosition(1, i + 1),
      })),
    ];

    const result = consolidateDurations(slots);

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ type: "note", duration: "1" });
  });

  it("should turn four quarter-spaced hits into four quarter notes", () => {
    const slots: Measure = [0, 4, 8, 12].map((index) => note(1, ...positionParts(index)));

    const result = consolidateDurations(slots);

    expect(result).toHaveLength(4);
    expect(result.every((slot) => slot.type === "note" && slot.duration === "4")).toBe(true);
  });

  it("should turn eight eighth-spaced hits into eight eighth notes", () => {
    const slots: Measure = [0, 2, 4, 6, 8, 10, 12, 14].map((index) => note(1, ...positionParts(index)));

    const result = consolidateDurations(slots);

    expect(result).toHaveLength(8);
    expect(result.every((slot) => slot.type === "note" && slot.duration === "8")).toBe(true);
  });

  it("should leave adjacent sixteenth-spaced hits as sixteenth notes", () => {
    const slots: Measure = [0, 1, 2, 3].map((index) => note(1, ...positionParts(index)));

    const result = consolidateDurations(slots);

    expect(result).toHaveLength(4);
    expect(result.every((slot) => slot.type === "note" && slot.duration === "16")).toBe(true);
  });

  it("should cap a note's extension at the alignment boundary instead of overrunning into a misaligned duration", () => {
    // A note at sixteenth-index 2 (beat 1, subdivision 2) followed by rests to the
    // end of the measure can only become an eighth note (index 2 is a multiple of
    // 2 but not of 4/8/16), even though 13 trailing rests would otherwise fit a
    // much longer duration.
    const slots: Measure = [
      note(1, 1, 2),
      ...Array.from({ length: 13 }, (_, i) => ({
        type: "rest" as const,
        id: `r${i}`,
        duration: "16",
        position: toPosition(1, i + 3),
      })),
    ];

    const result = consolidateDurations(slots);

    expect(result[0]).toMatchObject({ type: "note", duration: "8" });
  });

  it("should preserve every hit's id, sourceEventId, and time when extending a note's duration", () => {
    const original = note(1, 1, 0);
    const slots: Measure = [
      original,
      ...Array.from({ length: 3 }, (_, i) => ({
        type: "rest" as const,
        id: `r${i}`,
        duration: "16",
        position: toPosition(1, i + 1),
      })),
    ];

    const result = consolidateDurations(slots);

    expect(result[0]).toMatchObject({ type: "note", duration: "4", hits: original.hits });
  });

  it("should not touch rests that never follow a note", () => {
    const slots: Measure = Array.from({ length: 16 }, (_, i) => ({
      type: "rest" as const,
      id: `r${i}`,
      duration: "16",
      position: toPosition(1, i),
    }));

    const result = consolidateDurations(slots);

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ type: "rest", duration: "1" });
  });
});
