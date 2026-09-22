import { Stem } from "vexflow";

import type { ScoreHit } from "@/lib/score/types";
import { buildStaveNote } from "../buildStaveNote";

function hit(overrides: Partial<ScoreHit>): ScoreHit {
  return {
    id: "h",
    sourceEventId: "e",
    time: 0,
    instrument: "kick",
    confidence: null,
    provenance: "drumscript",
    ...overrides,
  };
}

describe("buildStaveNote", () => {
  it("should force an upward stem for a kick-only note", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ instrument: "kick" })],
    });

    expect(note.getStemDirection()).toBe(Stem.UP);
  });

  it("should force an upward stem for a snare-only note", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ instrument: "snare" })],
    });

    expect(note.getStemDirection()).toBe(Stem.UP);
  });

  it("should force an upward stem even for a kick+snare+hihat chord", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [
        hit({ id: "h1", instrument: "kick" }),
        hit({ id: "h2", instrument: "snare" }),
        hit({ id: "h3", instrument: "hihat_closed" }),
      ],
    });

    expect(note.getStemDirection()).toBe(Stem.UP);
    expect(note.getKeys()).toEqual(["f/4", "c/5", "g/5/x2"]);
  });

  it("should build a rest for a rest slot", () => {
    const note = buildStaveNote({
      type: "rest",
      id: "r",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
    });

    expect(note.isRest()).toBe(true);
  });

  it("should attach an articulation for an open hi-hat", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ instrument: "hihat_open" })],
    });

    expect(note.getModifiersByType("Articulation")).toHaveLength(1);
  });

  it("should deduplicate identical instruments among simultaneous hits", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ id: "h1", instrument: "kick" }), hit({ id: "h2", instrument: "kick" })],
    });

    expect(note.getKeys()).toEqual(["f/4"]);
  });
});
