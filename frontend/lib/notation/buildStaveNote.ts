import { Articulation, StaveNote } from "vexflow";

import type { Slot } from "@/lib/score/types";
import { INSTRUMENT_NOTATION } from "./instrumentNotation";

export function buildStaveNote(slot: Slot): StaveNote {
  if (slot.type === "rest") {
    return new StaveNote({ keys: ["b/4"], duration: `${slot.duration}r` });
  }

  const instruments = Array.from(new Set(slot.hits.map((hit) => hit.instrument)));

  const note = new StaveNote({
    keys: instruments.map((instrument) => INSTRUMENT_NOTATION[instrument].key),
    duration: slot.duration,
    stemDirection: 1,
    autoStem: false,
  });

  instruments
    .map((instrument) => INSTRUMENT_NOTATION[instrument].articulation)
    .filter((articulation): articulation is string => Boolean(articulation))
    .forEach((articulation) => {
      note.addModifier(new Articulation(articulation));
    });

  return note;
}
