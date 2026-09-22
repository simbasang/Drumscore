import type { AnalysisEvent } from "@/lib/api/jobs";
import { BEATS_PER_MEASURE, consolidateRests, SLOT_DURATION, SUBDIVISIONS_PER_BEAT } from "./grid";
import { generateId } from "./id";
import type { Measure, MusicalPosition, Score, ScoreNote, Slot } from "./types";

export function fromAnalysisEvents(events: AnalysisEvent[]): Score {
  const placeable = events.filter(
    (event): event is AnalysisEvent & { measure: number; beat: number; subdivision: number } =>
      event.measure != null && event.beat != null && event.subdivision != null,
  );

  if (placeable.length === 0) {
    return { measures: [] };
  }

  const grouped = new Map<string, AnalysisEvent[]>();
  for (const event of placeable) {
    const key = `${event.measure}:${event.beat}:${event.subdivision}`;
    const slotEvents = grouped.get(key);
    if (slotEvents) {
      slotEvents.push(event);
    } else {
      grouped.set(key, [event]);
    }
  }

  const maxMeasure = Math.max(...placeable.map((event) => event.measure));

  const measures: Measure[] = [];
  for (let measure = 1; measure <= maxMeasure; measure++) {
    const slots: Slot[] = [];

    for (let beat = 1; beat <= BEATS_PER_MEASURE; beat++) {
      for (let subdivision = 0; subdivision < SUBDIVISIONS_PER_BEAT; subdivision++) {
        const position: MusicalPosition = { measure, beat, subdivision };
        const slotEvents = grouped.get(`${measure}:${beat}:${subdivision}`);
        slots.push(
          slotEvents
            ? buildScoreNote(slotEvents, position)
            : { type: "rest", id: generateId("rest"), duration: SLOT_DURATION, position },
        );
      }
    }

    measures.push(consolidateRests(slots));
  }

  return { measures };
}

function buildScoreNote(slotEvents: AnalysisEvent[], position: MusicalPosition): ScoreNote {
  return {
    type: "note",
    id: generateId("note"),
    position,
    duration: SLOT_DURATION,
    hits: slotEvents.map((event) => ({
      id: generateId("hit"),
      sourceEventId: event.id,
      time: event.time,
      instrument: event.instrument,
      confidence: event.confidence,
      provenance: event.provenance ?? "unknown",
    })),
  };
}
