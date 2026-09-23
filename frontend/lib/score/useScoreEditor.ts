import { useState } from "react";

import type { AnalysisEvent, DrumInstrument } from "@/lib/api/jobs";
import { fromAnalysisEvents } from "./buildScore";
import { BEATS_PER_MEASURE, consolidateRests, SLOT_DURATION, SUBDIVISIONS_PER_BEAT, toPosition } from "./grid";
import { generateId } from "./id";
import { addHit, changeInstrument, deleteHit, moveHit } from "./transformations";
import type { Measure, MusicalPosition, Score } from "./types";

// fromAnalysisEvents([]) (or any events array with nothing placeable) yields
// a zero-measure score. insertHit (transformations.ts, shared by addHit and
// moveHit) only ever maps over score.measures's *existing* entries - it
// can't grow the array (see TECHNICAL_DEBT.md's "insertHit cannot create a
// new measure") - so addHit on a zero-measure score is silently a no-op,
// which would make the correction editor unusable on a from-scratch score
// (nothing transcribed yet, or every event filtered out). Seeding one empty
// (all-rest) measure gives the editor a first measure to place manual hits
// into, using the same building blocks buildScore.ts itself builds
// measures from - transformations.ts/buildScore.ts are untouched. Run
// through consolidateRests (the same call every other all-rest measure in
// this codebase goes through - buildScore.ts's consolidateDurations, and
// transformations.ts's post-edit consolidateDurations calls) so this seeded
// measure renders as one whole rest instead of 16 separate sixteenth rests,
// per CLAUDE.md's "musical note/rest durations instead of every hit as a
// sixteenth" mandate.
function emptyMeasure(measureNumber: number): Measure {
  const sixteenthRests = Array.from({ length: BEATS_PER_MEASURE * SUBDIVISIONS_PER_BEAT }, (_, sixteenthIndex) => ({
    type: "rest" as const,
    id: generateId("rest"),
    duration: SLOT_DURATION,
    position: toPosition(measureNumber, sixteenthIndex),
  }));
  return consolidateRests(sixteenthRests);
}

function buildInitialScore(events: AnalysisEvent[]): Score {
  const score = fromAnalysisEvents(events);
  return score.measures.length > 0 ? score : { measures: [emptyMeasure(1)] };
}

// Compares by event identity (id sequence), not array reference. A caller
// (e.g. Player.tsx) may reasonably pass a freshly-constructed array each
// render for the same underlying song (a `?? []` fallback, a `.filter()`,
// etc.) - reference equality would treat that as "a new song" every render
// and reset editor state (and, inside a render-phase state adjustment,
// infinite-loop). Comparing the same length and same ids in the same order
// is a cheap, sufficient proxy for "this is the same events list".
function sameEvents(a: AnalysisEvent[], b: AnalysisEvent[]): boolean {
  if (a === b) {
    return true;
  }
  if (a.length !== b.length) {
    return false;
  }
  return a.every((event, index) => event.id === b[index].id);
}

export interface ScoreEditor {
  score: Score;
  addHit: (position: MusicalPosition, instrument: DrumInstrument) => void;
  deleteHit: (hitId: string) => void;
  moveHit: (hitId: string, newPosition: MusicalPosition) => void;
  changeInstrument: (hitId: string, newInstrument: DrumInstrument) => void;
  undo: () => void;
  redo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}

export function useScoreEditor(events: AnalysisEvent[]): ScoreEditor {
  const [score, setScore] = useState<Score>(() => buildInitialScore(events));
  const [undoStack, setUndoStack] = useState<Score[]>([]);
  const [redoStack, setRedoStack] = useState<Score[]>([]);
  const [trackedEvents, setTrackedEvents] = useState(events);

  // Re-baselines when a genuinely new job's events arrive (a different
  // AnalysisEvent[] content, per sameEvents above) - there is nothing to
  // preserve across an entirely different song. React's documented
  // "adjusting state when a prop changes" pattern (storing the previous
  // value to compare against in state, not a ref - refs must not be read
  // during render): detected and applied synchronously during render, so
  // the very first render (trackedEvents initialized to the same `events`
  // reference) never redundantly rebuilds.
  if (!sameEvents(trackedEvents, events)) {
    setTrackedEvents(events);
    setScore(buildInitialScore(events));
    setUndoStack([]);
    setRedoStack([]);
  }

  function applyEdit(next: Score): void {
    setUndoStack((stack) => [...stack, score]);
    setRedoStack([]);
    setScore(next);
  }

  return {
    score,
    addHit: (position, instrument) => applyEdit(addHit(score, position, instrument)),
    deleteHit: (hitId) => applyEdit(deleteHit(score, hitId)),
    moveHit: (hitId, newPosition) => applyEdit(moveHit(score, hitId, newPosition)),
    changeInstrument: (hitId, newInstrument) => applyEdit(changeInstrument(score, hitId, newInstrument)),
    undo: () => {
      setUndoStack((stack) => {
        if (stack.length === 0) {
          return stack;
        }
        const previous = stack[stack.length - 1];
        setRedoStack((redo) => [...redo, score]);
        setScore(previous);
        return stack.slice(0, -1);
      });
    },
    redo: () => {
      setRedoStack((stack) => {
        if (stack.length === 0) {
          return stack;
        }
        const next = stack[stack.length - 1];
        setUndoStack((undo) => [...undo, score]);
        setScore(next);
        return stack.slice(0, -1);
      });
    },
    canUndo: undoStack.length > 0,
    canRedo: redoStack.length > 0,
  };
}
