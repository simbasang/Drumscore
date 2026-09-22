import type { Measure, Slot } from "@/lib/score/types";

const BEAMABLE_DURATIONS = new Set(["8", "16"]);

function isBeamable(slot: Slot): boolean {
  return slot.type === "note" && BEAMABLE_DURATIONS.has(slot.duration);
}

// Explicit drum-engraving beam grouping: consecutive eighth/sixteenth notes
// beam together only while they share the same beat (the quarter-note pulse)
// and there's no rest or non-beamable (quarter/half/whole) note between them.
// A group of a single note is dropped - convention (and VexFlow) never beams
// one note alone. This replaces relying on VexFlow's own
// Beam.generateBeams/groups-fraction heuristic with a rule this project owns
// and can test directly, per V1-019/#52.
export function computeBeamGroupIndices(measure: Measure): number[][] {
  const groups: number[][] = [];
  let current: number[] = [];
  let currentBeat: number | null = null;

  const flush = () => {
    if (current.length >= 2) {
      groups.push(current);
    }
    current = [];
  };

  measure.forEach((slot, index) => {
    if (!isBeamable(slot) || slot.position.beat !== currentBeat) {
      flush();
    }

    if (isBeamable(slot)) {
      if (current.length === 0) {
        currentBeat = slot.position.beat;
      }
      current.push(index);
    } else {
      currentBeat = null;
    }
  });
  flush();

  return groups;
}
