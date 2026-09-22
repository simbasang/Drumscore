import type { AnalysisEvent } from "@/lib/api/jobs";
import { fromAnalysisEvents } from "../buildScore";
import type { Measure } from "../types";

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

const DURATION_SIXTEENTHS: Record<string, number> = { "1": 16, "2": 8, "4": 4, "8": 2, "16": 1 };

function totalSixteenths(measure: Measure): number {
  return measure.reduce((sum, slot) => sum + DURATION_SIXTEENTHS[slot.duration], 0);
}

describe("fromAnalysisEvents", () => {
  it("should return no measures for no events", () => {
    const score = fromAnalysisEvents([]);

    expect(score).toEqual({ measures: [] });
  });

  it("should consolidate an entirely empty measure into a single whole rest", () => {
    const score = fromAnalysisEvents([event({ instrument: "kick", measure: 2, beat: 1, subdivision: 0 })]);

    expect(score.measures[0]).toEqual([
      { type: "rest", id: expect.any(String), duration: "1", position: { measure: 1, beat: 1, subdivision: 0 } },
    ]);
  });

  it("should extend a single event's note to fill the rest of an otherwise-empty measure", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0, time: 0.1, confidence: 0.8 }),
    ]);

    expect(score.measures[0]).toEqual([
      {
        type: "note",
        id: expect.any(String),
        position: { measure: 1, beat: 1, subdivision: 0 },
        duration: "1",
        hits: [
          {
            id: expect.any(String),
            sourceEventId: "a",
            time: 0.1,
            instrument: "kick",
            confidence: 0.8,
            provenance: "drumscript",
          },
        ],
      },
    ]);
  });

  it("should render a four-on-the-floor kick groove as quarter notes", () => {
    const score = fromAnalysisEvents(
      [1, 2, 3, 4].map((beat) => event({ id: `k${beat}`, instrument: "kick", beat, subdivision: 0 })),
    );

    expect(score.measures[0]).toHaveLength(4);
    expect(score.measures[0].every((slot) => slot.type === "note" && slot.duration === "4")).toBe(true);
  });

  it("should render a steady eighth-note hi-hat groove as eighth notes", () => {
    const positions = [0, 1, 2, 3].flatMap((beat) => [
      { beat: beat + 1, subdivision: 0 },
      { beat: beat + 1, subdivision: 2 },
    ]);
    const score = fromAnalysisEvents(
      positions.map((p, i) => event({ id: `h${i}`, instrument: "hihat_closed", ...p })),
    );

    expect(score.measures[0]).toHaveLength(8);
    expect(score.measures[0].every((slot) => slot.type === "note" && slot.duration === "8")).toBe(true);
  });

  it("should render a sixteenth-note hi-hat groove as sixteenth notes with no consolidation", () => {
    const score = fromAnalysisEvents(
      Array.from({ length: 16 }, (_, subdivision) =>
        event({ id: `h${subdivision}`, instrument: "hihat_closed", beat: Math.floor(subdivision / 4) + 1, subdivision: subdivision % 4 }),
      ),
    );

    expect(score.measures[0]).toHaveLength(16);
    expect(score.measures[0].every((slot) => slot.type === "note" && slot.duration === "16")).toBe(true);
  });

  it("should render a kick-and-backbeat-snare groove as quarter notes on the hits and a consolidated rest between", () => {
    const score = fromAnalysisEvents([
      event({ id: "k1", instrument: "kick", beat: 1, subdivision: 0 }),
      event({ id: "s1", instrument: "snare", beat: 2, subdivision: 0 }),
    ]);

    expect(score.measures[0]).toEqual([
      expect.objectContaining({ type: "note", duration: "4", position: { measure: 1, beat: 1, subdivision: 0 } }),
      expect.objectContaining({ type: "note", duration: "4", position: { measure: 1, beat: 2, subdivision: 0 } }),
      expect.objectContaining({ type: "rest", duration: "2", position: { measure: 1, beat: 3, subdivision: 0 } }),
    ]);
  });

  it("should combine simultaneous instruments into a single note with multiple hits", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0 }),
      event({ id: "b", instrument: "hihat_closed", beat: 1, subdivision: 0 }),
    ]);

    const note = score.measures[0][0] as { type: string; hits: { instrument: string }[] };
    expect(note.type).toBe("note");
    expect(note.hits.map((hit) => hit.instrument)).toEqual(["kick", "hihat_closed"]);
  });

  it("should preserve both hits, with their own source links, when two events share an instrument and position", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0 }),
      event({ id: "b", instrument: "kick", beat: 1, subdivision: 0 }),
    ]);

    const note = score.measures[0][0] as { type: string; hits: { sourceEventId: string | null }[] };
    expect(note.type).toBe("note");
    expect(note.hits.map((hit) => hit.sourceEventId)).toEqual(["a", "b"]);
  });

  it("should keep a note at its correct metric position even after leading/trailing rests are consolidated", () => {
    const score = fromAnalysisEvents([event({ instrument: "snare", beat: 2, subdivision: 1 })]);

    const noteSlot = score.measures[0].find((slot) => slot.type === "note");
    expect(noteSlot?.position).toEqual({ measure: 1, beat: 2, subdivision: 1 });
  });

  it("should always account for exactly one measure's worth of duration, regardless of note placement", () => {
    const placements = [
      [{ beat: 1, subdivision: 0 }],
      [{ beat: 1, subdivision: 0 }, { beat: 3, subdivision: 0 }],
      [{ beat: 1, subdivision: 0 }, { beat: 2, subdivision: 0 }, { beat: 4, subdivision: 3 }],
    ];

    for (const placement of placements) {
      const score = fromAnalysisEvents(placement.map((p, i) => event({ id: `e${i}`, instrument: "kick", ...p })));

      expect(totalSixteenths(score.measures[0])).toBe(16);
    }
  });

  it("should produce one measure per distinct measure number, filling any gaps", () => {
    const score = fromAnalysisEvents([event({ instrument: "kick", measure: 2, beat: 1, subdivision: 0 })]);

    expect(score.measures).toHaveLength(2);
    expect(score.measures[0][0].type).toBe("rest");
    expect(score.measures[1][0].type).toBe("note");
  });

  it("should ignore events missing measure, beat, or subdivision", () => {
    const score = fromAnalysisEvents([event({ instrument: "kick", measure: null })]);

    expect(score.measures).toEqual([]);
  });

  it("should carry each hit's original source time through unmodified", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0, time: 12.34 }),
      event({ id: "b", instrument: "hihat_closed", beat: 1, subdivision: 0, time: 12.36 }),
    ]);

    const note = score.measures[0][0] as { type: string; hits: { time: number | null }[] };
    expect(note.hits.map((hit) => hit.time)).toEqual([12.34, 12.36]);
  });
});
