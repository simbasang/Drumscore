import type { AnalysisEvent } from "@/lib/api/jobs";
import { INSTRUMENT_NOTATION } from "./instrumentNotation";

export interface NoteSpec {
  type: "note";
  keys: string[];
  articulations: string[];
  duration: string;
}

export interface RestSpec {
  type: "rest";
  duration: string;
}

export type SlotSpec = NoteSpec | RestSpec;

export type MeasureSpec = SlotSpec[];

export const BEATS_PER_MEASURE = 4;
export const SUBDIVISIONS_PER_BEAT = 4;
const SLOT_DURATION = "16";

export function buildMeasures(events: AnalysisEvent[]): MeasureSpec[] {
  const placeable = events.filter(
    (event): event is AnalysisEvent & { measure: number; beat: number; subdivision: number } =>
      event.measure != null && event.beat != null && event.subdivision != null,
  );

  if (placeable.length === 0) {
    return [];
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

  const measures: MeasureSpec[] = [];
  for (let measure = 1; measure <= maxMeasure; measure++) {
    const slots: SlotSpec[] = [];

    for (let beat = 1; beat <= BEATS_PER_MEASURE; beat++) {
      for (let subdivision = 0; subdivision < SUBDIVISIONS_PER_BEAT; subdivision++) {
        const slotEvents = grouped.get(`${measure}:${beat}:${subdivision}`);
        slots.push(slotEvents ? buildNoteSpec(slotEvents) : { type: "rest", duration: SLOT_DURATION });
      }
    }

    measures.push(slots);
  }

  return measures;
}

function buildNoteSpec(slotEvents: AnalysisEvent[]): NoteSpec {
  const instruments = Array.from(new Set(slotEvents.map((event) => event.instrument)));

  return {
    type: "note",
    keys: instruments.map((instrument) => INSTRUMENT_NOTATION[instrument].key),
    articulations: instruments
      .map((instrument) => INSTRUMENT_NOTATION[instrument].articulation)
      .filter((articulation): articulation is string => Boolean(articulation)),
    duration: SLOT_DURATION,
  };
}
