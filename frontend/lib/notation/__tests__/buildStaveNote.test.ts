import { Stem } from "vexflow";

import { buildStaveNote } from "../buildStaveNote";

describe("buildStaveNote", () => {
  it("should force an upward stem for a kick-only note", () => {
    const note = buildStaveNote({ type: "note", keys: ["f/4"], articulations: [], duration: "16", startSixteenth: 0 });

    expect(note.getStemDirection()).toBe(Stem.UP);
  });

  it("should force an upward stem for a snare-only note", () => {
    const note = buildStaveNote({ type: "note", keys: ["c/5"], articulations: [], duration: "16", startSixteenth: 0 });

    expect(note.getStemDirection()).toBe(Stem.UP);
  });

  it("should force an upward stem even for a kick+snare+hihat chord", () => {
    const note = buildStaveNote({
      type: "note",
      keys: ["f/4", "c/5", "g/5/x2"],
      articulations: [],
      duration: "16",
    startSixteenth: 0,
    });

    expect(note.getStemDirection()).toBe(Stem.UP);
    expect(note.getKeys()).toEqual(["f/4", "c/5", "g/5/x2"]);
  });

  it("should build a rest for a rest slot", () => {
    const note = buildStaveNote({ type: "rest", duration: "16", startSixteenth: 0 });

    expect(note.isRest()).toBe(true);
  });

  it("should attach an articulation for an open hi-hat", () => {
    const note = buildStaveNote({
      type: "note",
      keys: ["g/5/x2"],
      articulations: ["ah"],
      duration: "16",
    startSixteenth: 0,
    });

    expect(note.getModifiersByType("Articulation")).toHaveLength(1);
  });
});
