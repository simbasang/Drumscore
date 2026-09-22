import { computeBeamGroupIndices } from "../beaming";
import type { Measure, Slot } from "@/lib/score/types";

function note(beat: number, subdivision: number, duration: string): Slot {
  return {
    type: "note",
    id: `n-${beat}-${subdivision}`,
    position: { measure: 1, beat, subdivision },
    duration,
    hits: [
      {
        id: `h-${beat}-${subdivision}`,
        sourceEventId: null,
        time: null,
        instrument: "hihat_closed",
        confidence: null,
        provenance: "test",
      },
    ],
  };
}

function rest(beat: number, subdivision: number, duration: string): Slot {
  return {
    type: "rest",
    id: `r-${beat}-${subdivision}`,
    position: { measure: 1, beat, subdivision },
    duration,
  };
}

describe("computeBeamGroupIndices", () => {
  it("should group a beat of four sixteenth notes into one beam", () => {
    const measure: Measure = [
      note(1, 0, "16"),
      note(1, 1, "16"),
      note(1, 2, "16"),
      note(1, 3, "16"),
    ];

    const groups = computeBeamGroupIndices(measure);

    expect(groups).toEqual([[0, 1, 2, 3]]);
  });

  it("should group a measure of straight eighth notes into one beam per beat", () => {
    const measure: Measure = [
      note(1, 0, "8"),
      note(1, 2, "8"),
      note(2, 0, "8"),
      note(2, 2, "8"),
      note(3, 0, "8"),
      note(3, 2, "8"),
      note(4, 0, "8"),
      note(4, 2, "8"),
    ];

    const groups = computeBeamGroupIndices(measure);

    expect(groups).toEqual([[0, 1], [2, 3], [4, 5], [6, 7]]);
  });

  it("should never beam across a beat boundary", () => {
    const measure: Measure = [note(1, 2, "8"), note(2, 0, "8")];

    const groups = computeBeamGroupIndices(measure);

    expect(groups).toEqual([]);
  });

  it("should not beam a lone eighth note surrounded by rests", () => {
    const measure: Measure = [rest(1, 0, "16"), note(1, 1, "8"), rest(1, 3, "16")];

    const groups = computeBeamGroupIndices(measure);

    expect(groups).toEqual([]);
  });

  it("should break the group at a quarter note and resume after it", () => {
    const measure: Measure = [note(1, 0, "4"), note(2, 0, "8"), note(2, 2, "8")];

    const groups = computeBeamGroupIndices(measure);

    expect(groups).toEqual([[1, 2]]);
  });

  it("should include a simultaneous-hit (chord) note in its beat's beam like any other note", () => {
    const chord: Slot = {
      type: "note",
      id: "chord",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "8",
      hits: [
        {
          id: "h1",
          sourceEventId: null,
          time: null,
          instrument: "kick",
          confidence: null,
          provenance: "test",
        },
        {
          id: "h2",
          sourceEventId: null,
          time: null,
          instrument: "hihat_closed",
          confidence: null,
          provenance: "test",
        },
      ],
    };
    const measure: Measure = [chord, note(1, 2, "8")];

    const groups = computeBeamGroupIndices(measure);

    expect(groups).toEqual([[0, 1]]);
  });

  it("should return no groups for an all-rest measure", () => {
    const measure: Measure = [rest(1, 0, "4"), rest(2, 0, "4"), rest(3, 0, "4"), rest(4, 0, "4")];

    const groups = computeBeamGroupIndices(measure);

    expect(groups).toEqual([]);
  });
});
