import { act, renderHook } from "@testing-library/react";
import React from "react";

import type { AnalysisEvent } from "@/lib/api/types";
import { useScoreEditor } from "../useScoreEditor";

function event(overrides: Partial<AnalysisEvent>): AnalysisEvent {
  return {
    id: "e",
    time: 0,
    instrument: "kick",
    confidence: null,
    provenance: "drumscript",
    measure: 1,
    beat: 1,
    subdivision: 0,
    ...overrides,
  };
}

describe("useScoreEditor", () => {
  it("should build the initial score from the given events", () => {
    const { result } = renderHook(() => useScoreEditor([event({ instrument: "kick", beat: 1, subdivision: 0 })]));

    const noteSlot = result.current.score.measures[0].find((slot) => slot.type === "note");
    expect(noteSlot).toBeDefined();
  });

  it("should seed a from-scratch score with a single consolidated whole-rest measure, not 16 separate sixteenth rests", () => {
    const { result } = renderHook(() => useScoreEditor([]));

    expect(result.current.score.measures).toHaveLength(1);
    expect(result.current.score.measures[0]).toHaveLength(1);
    expect(result.current.score.measures[0][0]).toMatchObject({ type: "rest", duration: "1" });
  });

  it("should apply addHit and reflect the new hit in the score", () => {
    const { result } = renderHook(() => useScoreEditor([]));

    act(() => {
      result.current.addHit({ measure: 1, beat: 1, subdivision: 0 }, "snare");
    });

    const noteSlot = result.current.score.measures[0].find((slot) => slot.type === "note");
    expect(noteSlot?.type).toBe("note");
  });

  it("should apply deleteHit by delegating to the underlying transformation", () => {
    const events = [event({ id: "a", instrument: "kick", beat: 1, subdivision: 0 })];
    const { result } = renderHook(() => useScoreEditor(events));
    const noteSlot = result.current.score.measures[0].find((slot) => slot.type === "note");
    const hitId = (noteSlot as { hits: { id: string }[] }).hits[0].id;

    act(() => {
      result.current.deleteHit(hitId);
    });

    const slot = result.current.score.measures[0].find((s) => s.position.beat === 1 && s.position.subdivision === 0);
    expect(slot?.type).toBe("rest");
  });

  it("should undo the most recent edit back to the previous score", () => {
    const events = [event({ id: "a", instrument: "kick", beat: 1, subdivision: 0 })];
    const { result } = renderHook(() => useScoreEditor(events));
    const scoreBeforeEdit = result.current.score;

    act(() => {
      result.current.addHit({ measure: 1, beat: 2, subdivision: 0 }, "snare");
    });
    expect(result.current.canUndo).toBe(true);

    act(() => {
      result.current.undo();
    });

    expect(result.current.score).toEqual(scoreBeforeEdit);
    expect(result.current.canUndo).toBe(false);
  });

  it("should redo an undone edit", () => {
    const { result } = renderHook(() => useScoreEditor([]));

    act(() => {
      result.current.addHit({ measure: 1, beat: 1, subdivision: 0 }, "snare");
    });
    const scoreAfterEdit = result.current.score;
    act(() => {
      result.current.undo();
    });
    expect(result.current.canRedo).toBe(true);

    act(() => {
      result.current.redo();
    });

    expect(result.current.score).toEqual(scoreAfterEdit);
    expect(result.current.canRedo).toBe(false);
  });

  it("should clear the redo stack when a new edit is made after an undo", () => {
    const { result } = renderHook(() => useScoreEditor([]));

    act(() => {
      result.current.addHit({ measure: 1, beat: 1, subdivision: 0 }, "snare");
    });
    act(() => {
      result.current.undo();
    });
    expect(result.current.canRedo).toBe(true);

    act(() => {
      result.current.addHit({ measure: 1, beat: 2, subdivision: 0 }, "kick");
    });

    expect(result.current.canRedo).toBe(false);
  });

  it("should do nothing when undo is called with an empty undo stack", () => {
    const { result } = renderHook(() => useScoreEditor([]));
    const initialScore = result.current.score;

    act(() => {
      result.current.undo();
    });

    expect(result.current.score).toBe(initialScore);
  });

  it("should move exactly one entry from the undo stack to the redo stack per undo() call under React Strict Mode", () => {
    // Strict Mode deliberately double-invokes reducers/updater functions in
    // development to surface impurity. The pre-refactor undo/redo (nested
    // setState-as-a-side-effect inside a setState updater) pushed the same
    // score onto the OTHER stack twice per call under that double
    // invocation - a plain canRedo/canUndo boolean check after a single
    // undo can't tell "1 entry" from "2 entries" apart (both are truthy),
    // so this asserts the stack is actually exhausted after exactly one
    // matching redo() call - the pre-refactor code left a duplicate
    // entry behind, requiring a second redo click to fully exhaust it.
    const { result } = renderHook(() => useScoreEditor([]), { wrapper: React.StrictMode });

    act(() => {
      result.current.addHit({ measure: 1, beat: 1, subdivision: 0 }, "snare");
    });
    expect(result.current.canUndo).toBe(true);

    act(() => {
      result.current.undo();
    });
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(true);

    act(() => {
      result.current.redo();
    });

    expect(result.current.canRedo).toBe(false);
  });

  it("should reset score and history when given a new events array", () => {
    const firstEvents = [event({ id: "a", instrument: "kick", beat: 1, subdivision: 0 })];
    const { result, rerender } = renderHook(({ events }) => useScoreEditor(events), {
      initialProps: { events: firstEvents },
    });
    act(() => {
      result.current.addHit({ measure: 1, beat: 2, subdivision: 0 }, "snare");
    });
    expect(result.current.canUndo).toBe(true);

    const secondEvents = [event({ id: "b", instrument: "snare", beat: 3, subdivision: 0 })];
    rerender({ events: secondEvents });

    expect(result.current.canUndo).toBe(false);
    const noteSlot = result.current.score.measures[0].find((slot) => slot.type === "note");
    expect(noteSlot?.type === "note" && noteSlot.hits[0].instrument).toBe("snare");
  });
});
