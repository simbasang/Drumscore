import { Articulation, StaveNote } from "vexflow";

import type { SlotSpec } from "./buildScore";

export function buildStaveNote(slot: SlotSpec): StaveNote {
  if (slot.type === "rest") {
    return new StaveNote({ keys: ["b/4"], duration: `${slot.duration}r` });
  }

  const note = new StaveNote({
    keys: slot.keys,
    duration: slot.duration,
    stemDirection: 1,
    autoStem: false,
  });

  slot.articulations.forEach((articulation) => {
    note.addModifier(new Articulation(articulation));
  });

  return note;
}
