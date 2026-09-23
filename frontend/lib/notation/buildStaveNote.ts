import { StaveNote } from "vexflow";

import { isLowConfidence } from "@/lib/score/confidence";
import type { Slot } from "@/lib/score/types";
import { INSTRUMENT_NOTATION } from "./instrumentNotation";

export const MANUAL_HIT_STYLE = { fillStyle: "#3182ce", strokeStyle: "#3182ce" };
export const LOW_CONFIDENCE_STYLE = { fillStyle: "#dd6b20", strokeStyle: "#dd6b20" };

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

  if (slot.hits.some((hit) => hit.sourceEventId == null)) {
    note.setStyle(MANUAL_HIT_STYLE);
  } else if (slot.hits.some((hit) => isLowConfidence(hit))) {
    note.setStyle(LOW_CONFIDENCE_STYLE);
  }

  return note;
}
