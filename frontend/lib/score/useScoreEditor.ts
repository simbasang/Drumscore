import { useReducer } from "react";

import type { AnalysisEvent, DrumInstrument } from "@/lib/api/types";
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

interface EditorState {
  score: Score;
  undoStack: Score[];
  redoStack: Score[];
  trackedEvents: AnalysisEvent[];
}

type EditorAction =
  | { type: "apply-edit"; next: Score }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "reset"; events: AnalysisEvent[]; score: Score };

// A pure reducer: every branch derives the next state only from (state,
// action), with no nested setState-as-a-side-effect calls. React's Strict
// Mode deliberately invokes reducers twice in development to catch exactly
// that kind of impurity - the previous nested-setState version of undo/redo
// each triggered a second state update as a side effect of computing the
// first, so double-invocation pushed the same score onto the other stack
// twice per call.
function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "apply-edit":
      return {
        ...state,
        score: action.next,
        undoStack: [...state.undoStack, state.score],
        redoStack: [],
      };
    case "undo": {
      if (state.undoStack.length === 0) {
        return state;
      }
      const previous = state.undoStack[state.undoStack.length - 1];
      return {
        ...state,
        score: previous,
        undoStack: state.undoStack.slice(0, -1),
        redoStack: [...state.redoStack, state.score],
      };
    }
    case "redo": {
      if (state.redoStack.length === 0) {
        return state;
      }
      const next = state.redoStack[state.redoStack.length - 1];
      return {
        ...state,
        score: next,
        redoStack: state.redoStack.slice(0, -1),
        undoStack: [...state.undoStack, state.score],
      };
    }
    case "reset":
      return { score: action.score, undoStack: [], redoStack: [], trackedEvents: action.events };
    default:
      return state;
  }
}

function initEditorState(initialEvents: AnalysisEvent[]): EditorState {
  return { score: buildInitialScore(initialEvents), undoStack: [], redoStack: [], trackedEvents: initialEvents };
}

export function useScoreEditor(events: AnalysisEvent[]): ScoreEditor {
  const [state, dispatch] = useReducer(editorReducer, events, initEditorState);
  const { score, undoStack, redoStack } = state;

  // Re-baselines when a genuinely new job's events arrive (a different
  // AnalysisEvent[] content, per sameEvents above) - there is nothing to
  // preserve across an entirely different song. React's documented
  // "adjusting state when a prop changes" pattern (storing the previous
  // value to compare against in state, not a ref - refs must not be read
  // during render): detected and applied synchronously during render, so
  // the very first render (trackedEvents initialized to the same `events`
  // reference) never redundantly rebuilds.
  if (!sameEvents(state.trackedEvents, events)) {
    dispatch({ type: "reset", events, score: buildInitialScore(events) });
  }

  function applyEdit(next: Score): void {
    dispatch({ type: "apply-edit", next });
  }

  return {
    score,
    addHit: (position, instrument) => applyEdit(addHit(score, position, instrument)),
    deleteHit: (hitId) => applyEdit(deleteHit(score, hitId)),
    moveHit: (hitId, newPosition) => applyEdit(moveHit(score, hitId, newPosition)),
    changeInstrument: (hitId, newInstrument) => applyEdit(changeInstrument(score, hitId, newInstrument)),
    undo: () => dispatch({ type: "undo" }),
    redo: () => dispatch({ type: "redo" }),
    canUndo: undoStack.length > 0,
    canRedo: redoStack.length > 0,
  };
}
