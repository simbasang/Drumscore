import type { DrumInstrument } from "@/lib/api/types";
import { consolidateDurations, expandMeasure, SLOT_DURATION, toSixteenthIndex } from "./grid";
import { generateId } from "./id";
import type { MusicalPosition, Score, ScoreHit, ScoreNote, Slot } from "./types";

export function addHit(score: Score, position: MusicalPosition, instrument: DrumInstrument): Score {
  const hit: ScoreHit = {
    id: generateId("hit"),
    sourceEventId: null,
    time: null,
    instrument,
    confidence: null,
    provenance: "manual",
  };

  return insertHit(score, position, hit);
}

export function deleteHit(score: Score, hitId: string): Score {
  const measures = score.measures.map((measure, index) => {
    const measureNumber = index + 1;
    const containsHit = measure.some((slot) => slot.type === "note" && slot.hits.some((hit) => hit.id === hitId));
    if (!containsHit) {
      return measure;
    }

    const expanded = expandMeasure(measure, measureNumber);
    const updated = expanded.map((slot): Slot => {
      if (slot.type !== "note") {
        return slot;
      }
      const hits = slot.hits.filter((hit) => hit.id !== hitId);
      if (hits.length === 0) {
        return { type: "rest", id: generateId("rest"), duration: SLOT_DURATION, position: slot.position };
      }
      return { ...slot, hits };
    });

    return consolidateDurations(updated);
  });

  return { measures };
}

export function moveHit(score: Score, hitId: string, newPosition: MusicalPosition): Score {
  const hit = findHit(score, hitId);
  if (!hit) {
    return score;
  }

  return insertHit(deleteHit(score, hitId), newPosition, hit);
}

export function changeInstrument(score: Score, hitId: string, newInstrument: DrumInstrument): Score {
  const measures = score.measures.map((measure) =>
    measure.map((slot): Slot => {
      if (slot.type !== "note") {
        return slot;
      }
      return {
        ...slot,
        hits: slot.hits.map((hit) => (hit.id === hitId ? { ...hit, instrument: newInstrument } : hit)),
      };
    }),
  );

  return { measures };
}

function insertHit(score: Score, position: MusicalPosition, hit: ScoreHit): Score {
  const measures = score.measures.map((measure, index) => {
    const measureNumber = index + 1;
    if (measureNumber !== position.measure) {
      return measure;
    }

    const expanded = expandMeasure(measure, measureNumber);
    const sixteenthIndex = toSixteenthIndex(position);
    const existing = expanded[sixteenthIndex];
    const note: ScoreNote =
      existing.type === "note"
        ? { ...existing, hits: [...existing.hits, hit] }
        : { type: "note", id: generateId("note"), position, duration: SLOT_DURATION, hits: [hit] };

    expanded[sixteenthIndex] = note;

    return consolidateDurations(expanded);
  });

  return { measures };
}

function findHit(score: Score, hitId: string): ScoreHit | undefined {
  for (const measure of score.measures) {
    for (const slot of measure) {
      if (slot.type === "note") {
        const hit = slot.hits.find((h) => h.id === hitId);
        if (hit) {
          return hit;
        }
      }
    }
  }
  return undefined;
}
