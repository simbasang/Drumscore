import { generateId } from "./id";
import type { Measure, MusicalPosition, Slot } from "./types";

export const BEATS_PER_MEASURE = 4;
export const SUBDIVISIONS_PER_BEAT = 4;
export const SLOT_DURATION = "16";
const SLOTS_PER_MEASURE = BEATS_PER_MEASURE * SUBDIVISIONS_PER_BEAT;

// Largest-to-smallest so consolidateRests always prefers the longest valid
// rest value, ordered with their duration in sixteenth-note units.
const REST_SIZES_SIXTEENTHS: { duration: string; sixteenths: number }[] = [
  { duration: "1", sixteenths: 16 },
  { duration: "2", sixteenths: 8 },
  { duration: "4", sixteenths: 4 },
  { duration: "8", sixteenths: 2 },
  { duration: "16", sixteenths: 1 },
];

export function toSixteenthIndex(position: MusicalPosition): number {
  return (position.beat - 1) * SUBDIVISIONS_PER_BEAT + position.subdivision;
}

export function toPosition(measure: number, sixteenthIndex: number): MusicalPosition {
  return {
    measure,
    beat: Math.floor(sixteenthIndex / SUBDIVISIONS_PER_BEAT) + 1,
    subdivision: sixteenthIndex % SUBDIVISIONS_PER_BEAT,
  };
}

// Merges each run of consecutive single-sixteenth rests into the fewest rest
// values that tie together correctly, each aligned so its start position is
// a multiple of its own duration (e.g. a half rest only ever starts on beat
// 1 or 3 of a 4/4 measure) - the engraving convention that keeps rests
// readable instead of an arbitrary run of 16th rests.
export function consolidateRests(slots: Slot[]): Slot[] {
  const result: Slot[] = [];
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

    const measure = slots[i].position.measure;
    let sixteenthIndex = toSixteenthIndex(slots[i].position);
    let remaining = runLength;
    while (remaining > 0) {
      // The smallest entry (a 16th rest, 1 sixteenth long) always matches
      // here, since sixteenthIndex % 1 is always 0 - .find() can never fall
      // through without a match while remaining > 0.
      const size = REST_SIZES_SIXTEENTHS.find(
        ({ sixteenths }) => sixteenths <= remaining && sixteenthIndex % sixteenths === 0,
      )!;
      result.push({
        type: "rest",
        id: generateId("rest"),
        duration: size.duration,
        position: toPosition(measure, sixteenthIndex),
      });
      sixteenthIndex += size.sixteenths;
      remaining -= size.sixteenths;
    }

    i += runLength;
  }

  return result;
}

// Expands an already-consolidated measure back to one slot per sixteenth,
// so a transformation can edit a single slot before re-consolidating. Every
// note in `measure` occupies exactly one sixteenth (durations aren't
// consolidated across notes yet - that's V1-018/#51), so this only needs to
// place each note at its own index and fill every other index with a fresh
// single-sixteenth rest; existing rest slots in `measure` are discarded and
// rebuilt, since consolidateRests will regenerate them anyway.
export function expandMeasure(measure: Measure, measureNumber: number): Slot[] {
  const bySixteenthIndex = new Map<number, Slot>();
  for (const slot of measure) {
    if (slot.type === "note") {
      bySixteenthIndex.set(toSixteenthIndex(slot.position), slot);
    }
  }

  return Array.from({ length: SLOTS_PER_MEASURE }, (_, index) => {
    const existing = bySixteenthIndex.get(index);
    if (existing) {
      return existing;
    }
    return {
      type: "rest",
      id: generateId("rest"),
      duration: SLOT_DURATION,
      position: toPosition(measureNumber, index),
    };
  });
}
