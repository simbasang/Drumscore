import { Stem } from "vexflow";

import type { ScoreHit } from "@/lib/score/types";
import { buildStaveNote, LOW_CONFIDENCE_STYLE, MANUAL_HIT_STYLE } from "../buildStaveNote";

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

  it("should use a circled-X notehead for an open hi-hat", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ instrument: "hihat_open" })],
    });

    expect(note.getKeys()).toEqual(["g/5/x3"]);
  });

  it("should use different noteheads for open vs. closed hi-hat", () => {
    const closed = buildStaveNote({
      type: "note",
      id: "n1",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ instrument: "hihat_closed" })],
    });
    const open = buildStaveNote({
      type: "note",
      id: "n2",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ instrument: "hihat_open" })],
    });

    expect(closed.getKeys()).not.toEqual(open.getKeys());
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

describe("buildStaveNote manual/low-confidence styling", () => {
  it("should apply the manual-hit style when a hit has no source event", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ sourceEventId: null })],
    });

    expect(note.getStyle()).toMatchObject(MANUAL_HIT_STYLE);
  });

  it("should apply the low-confidence style when a hit is below the confidence threshold", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ sourceEventId: "e", confidence: 0.1 })],
    });

    expect(note.getStyle()).toMatchObject(LOW_CONFIDENCE_STYLE);
  });

  it("should apply no style override for an ordinary transcribed hit", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ sourceEventId: "e", confidence: 0.9 })],
    });

    // VexFlow's Element base class always initializes `style` from
    // Metrics.getStyle(category) (see node_modules/vexflow Element
    // constructor), so an untouched StaveNote's getStyle() is `{}`, not
    // `undefined` - there is no VexFlow-level default style registered
    // for the "StaveNote" category.
    expect(note.getStyle()).toEqual({});
  });

  it("should prefer the manual style over the low-confidence style when a note has both", () => {
    const note = buildStaveNote({
      type: "note",
      id: "n",
      position: { measure: 1, beat: 1, subdivision: 0 },
      duration: "16",
      hits: [hit({ id: "h1", sourceEventId: null }), hit({ id: "h2", sourceEventId: "e", confidence: 0.1 })],
    });

    expect(note.getStyle()).toMatchObject(MANUAL_HIT_STYLE);
  });
});
