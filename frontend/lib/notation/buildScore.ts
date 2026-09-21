import type { AnalysisEvent } from "@/lib/api/jobs";
import { INSTRUMENT_NOTATION } from "./instrumentNotation";

export interface NoteSpec {
  type: "note";
  keys: string[];
  articulations: string[];
  duration: string;
  startSixteenth: number;
  sourceTimes: number[];
}

export interface RestSpec {
  type: "rest";
  duration: string;
  startSixteenth: number;
}

export type SlotSpec = NoteSpec | RestSpec;

export type MeasureSpec = SlotSpec[];

export const BEATS_PER_MEASURE = 4;
export const SUBDIVISIONS_PER_BEAT = 4;
const SLOT_DURATION = "16";

// Largest-to-smallest so consolidateRests always prefers the longest valid
// rest value, ordered with their duration in sixteenth-note units.
const REST_SIZES_SIXTEENTHS: { duration: string; sixteenths: number }[] = [
  { duration: "1", sixteenths: 16 },
  { duration: "2", sixteenths: 8 },
  { duration: "4", sixteenths: 4 },
  { duration: "8", sixteenths: 2 },
  { duration: "16", sixteenths: 1 },
];

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
        const startSixteenth = (beat - 1) * SUBDIVISIONS_PER_BEAT + subdivision;
        const slotEvents = grouped.get(`${measure}:${beat}:${subdivision}`);
        slots.push(
          slotEvents
            ? buildNoteSpec(slotEvents, startSixteenth)
            : { type: "rest", duration: SLOT_DURATION, startSixteenth },
        );
      }
    }

    measures.push(consolidateRests(slots));
  }

  return measures;
}

function buildNoteSpec(slotEvents: AnalysisEvent[], startSixteenth: number): NoteSpec {
  const instruments = Array.from(new Set(slotEvents.map((event) => event.instrument)));

  return {
    type: "note",
    keys: instruments.map((instrument) => INSTRUMENT_NOTATION[instrument].key),
    articulations: instruments
      .map((instrument) => INSTRUMENT_NOTATION[instrument].articulation)
      .filter((articulation): articulation is string => Boolean(articulation)),
    duration: SLOT_DURATION,
    startSixteenth,
    sourceTimes: slotEvents.map((event) => event.time),
  };
}

// Merges each run of consecutive 16th-note rests into the fewest rest
// values that tie together correctly, each aligned so its start position is
// a multiple of its own duration (e.g. a half rest only ever starts on beat
// 1 or 3 of a 4/4 measure) - the engraving convention that keeps rests
// readable instead of an arbitrary run of 16th rests.
function consolidateRests(slots: SlotSpec[]): SlotSpec[] {
  const result: SlotSpec[] = [];
  let i = 0;

  while (i < slots.length) {
    if (slots[i].type === "note") {
      result.push(slots[i]);
      i++;
      continue;
    }

    let runLength = 0;
    while (i + runLength < slots.length && slots[i + runLength].type === "rest") {
      runLength++;
    }

    let position = slots[i].startSixteenth;
    let remaining = runLength;
    while (remaining > 0) {
      // The smallest entry (a 16th rest, 1 sixteenth long) always matches
      // here, since position % 1 is always 0 - .find() can never fall
      // through without a match while remaining > 0.
      const size = REST_SIZES_SIXTEENTHS.find(
        ({ sixteenths }) => sixteenths <= remaining && position % sixteenths === 0,
      )!;
      result.push({ type: "rest", duration: size.duration, startSixteenth: position });
      position += size.sixteenths;
      remaining -= size.sixteenths;
    }

    i += runLength;
  }

  return result;
}
