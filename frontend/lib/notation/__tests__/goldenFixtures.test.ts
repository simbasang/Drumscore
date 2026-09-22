import { Stem } from "vexflow";

import { fromAnalysisEvents } from "@/lib/score/buildScore";
import type { ScoreNote, Slot } from "@/lib/score/types";
import { GROOVE_FIXTURES, groove } from "../__fixtures__/grooves";
import { buildStaveNote } from "../buildStaveNote";
import { INSTRUMENT_NOTATION } from "../instrumentNotation";

function allSlots(events: Parameters<typeof fromAnalysisEvents>[0]): Slot[] {
  return fromAnalysisEvents(events).measures.flat();
}

function notesOnly(slots: Slot[]): ScoreNote[] {
  return slots.filter((slot): slot is ScoreNote => slot.type === "note");
}

describe("GROOVE_FIXTURES", () => {
  it("should include one fixture for each representative groove category", () => {
    const names = GROOVE_FIXTURES.map((fixture) => fixture.name);

    expect(names).toEqual([
      "sparseBackbeat",
      "denseSixteenths",
      "restStretch",
      "simultaneousHits",
      "openHihatAlternation",
      "tomFill",
    ]);
  });

  it.each(GROOVE_FIXTURES.map((fixture) => [fixture.name, fixture] as const))(
    "should force every note's stem upward in %s",
    (_name, fixture) => {
      const notes = notesOnly(allSlots(fixture.events));

      expect(notes.length).toBeGreaterThan(0);
      for (const note of notes) {
        expect(buildStaveNote(note).getStemDirection()).toBe(Stem.UP);
      }
    },
  );

  it("should group kick+snare+hihat into one simultaneous note for simultaneousHits", () => {
    const notes = notesOnly(allSlots(groove("simultaneousHits").events));

    expect(notes).toHaveLength(1);
    expect(new Set(notes[0].hits.map((hit) => hit.instrument))).toEqual(
      new Set(["kick", "snare", "hihat_closed"]),
    );
  });

  it("should render a single isolated hit as a quarter note surrounded by consolidated rests for restStretch", () => {
    const slots = allSlots(groove("restStretch").events);

    expect(slots.map((slot) => ({ type: slot.type, duration: slot.duration }))).toEqual([
      { type: "rest", duration: "4" },
      { type: "note", duration: "4" },
      { type: "rest", duration: "2" },
    ]);
  });

  it("should leave every sixteenth-note slot as a note with no rests for denseSixteenths", () => {
    const slots = allSlots(groove("denseSixteenths").events);

    expect(slots).toHaveLength(16);
    expect(slots.every((slot) => slot.type === "note" && slot.duration === "16")).toBe(true);
  });

  it("should give alternating closed/open hi-hat notes distinct noteheads at the same pitch for openHihatAlternation", () => {
    const notes = notesOnly(allSlots(groove("openHihatAlternation").events));

    const keys = notes.map((note) => buildStaveNote(note).getKeys());

    expect(keys).toEqual([
      [INSTRUMENT_NOTATION.hihat_closed.key],
      [INSTRUMENT_NOTATION.hihat_open.key],
      [INSTRUMENT_NOTATION.hihat_closed.key],
      [INSTRUMENT_NOTATION.hihat_open.key],
    ]);
  });

  it("should place four distinct sixteenth-note voices across the fill beat for tomFill", () => {
    const notes = notesOnly(allSlots(groove("tomFill").events));
    const fillNotes = notes.filter((note) => note.position.beat === 4);

    expect(fillNotes.map((note) => note.hits[0].instrument)).toEqual([
      "tom_high",
      "tom_mid",
      "tom_low",
      "snare",
    ]);
    expect(fillNotes.every((note) => note.duration === "16")).toBe(true);
  });
});
