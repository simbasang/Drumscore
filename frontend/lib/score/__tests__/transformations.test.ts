import type { AnalysisEvent } from "@/lib/api/jobs";
import { fromAnalysisEvents } from "../buildScore";
import { addHit, changeInstrument, deleteHit, moveHit } from "../transformations";
import type { Score, ScoreHit } from "../types";

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

function hitsAt(score: Score, measure: number, beat: number, subdivision: number): ScoreHit[] {
  const slot = score.measures[measure - 1].find(
    (s) => s.position.beat === beat && s.position.subdivision === subdivision,
  );
  return slot?.type === "note" ? slot.hits : [];
}

describe("addHit", () => {
  it("should add a manually-added hit at an empty position", () => {
    const score = fromAnalysisEvents([event({ instrument: "kick", beat: 1, subdivision: 0 })]);

    const updated = addHit(score, { measure: 1, beat: 2, subdivision: 0 }, "snare");

    const hits = hitsAt(updated, 1, 2, 0);
    expect(hits).toHaveLength(1);
    expect(hits[0]).toMatchObject({ instrument: "snare", sourceEventId: null, time: null, provenance: "manual" });
  });

  it("should join an existing note as a second simultaneous hit", () => {
    const score = fromAnalysisEvents([event({ instrument: "kick", beat: 1, subdivision: 0 })]);

    const updated = addHit(score, { measure: 1, beat: 1, subdivision: 0 }, "hihat_closed");

    const hits = hitsAt(updated, 1, 1, 0);
    expect(hits.map((hit) => hit.instrument)).toEqual(["kick", "hihat_closed"]);
  });
});

describe("deleteHit", () => {
  it("should turn a single-hit note back into a rest", () => {
    const score = fromAnalysisEvents([event({ instrument: "kick", beat: 1, subdivision: 0 })]);
    const hitId = hitsAt(score, 1, 1, 0)[0].id;

    const updated = deleteHit(score, hitId);

    const slot = updated.measures[0].find((s) => s.position.beat === 1 && s.position.subdivision === 0);
    expect(slot?.type).toBe("rest");
  });

  it("should leave the remaining hit behind when deleting one of two simultaneous hits", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0 }),
      event({ id: "b", instrument: "snare", beat: 1, subdivision: 0 }),
    ]);
    const kickHitId = hitsAt(score, 1, 1, 0).find((hit) => hit.instrument === "kick")!.id;

    const updated = deleteHit(score, kickHitId);

    expect(hitsAt(updated, 1, 1, 0).map((hit) => hit.instrument)).toEqual(["snare"]);
  });
});

describe("moveHit", () => {
  it("should relocate a hit to a new position while preserving its id, source link, and time", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0, time: 1.5 }),
    ]);
    const original = hitsAt(score, 1, 1, 0)[0];

    const updated = moveHit(score, original.id, { measure: 1, beat: 3, subdivision: 0 });

    expect(hitsAt(updated, 1, 1, 0)).toHaveLength(0);
    expect(hitsAt(updated, 1, 3, 0)[0]).toEqual(original);
  });
});

describe("changeInstrument", () => {
  it("should update a hit's instrument without changing its position or source link", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0, time: 0.5 }),
    ]);
    const original = hitsAt(score, 1, 1, 0)[0];

    const updated = changeInstrument(score, original.id, "tom_low");

    expect(hitsAt(updated, 1, 1, 0)[0]).toEqual({ ...original, instrument: "tom_low" });
  });
});

describe("source link preservation", () => {
  it("should leave every other hit's id, sourceEventId, and time unchanged when one hit is edited", () => {
    const score = fromAnalysisEvents([
      event({ id: "a", instrument: "kick", beat: 1, subdivision: 0, time: 0 }),
      event({ id: "b", instrument: "snare", beat: 2, subdivision: 0, time: 0.5 }),
    ]);
    const untouched = hitsAt(score, 1, 2, 0)[0];
    const targetId = hitsAt(score, 1, 1, 0)[0].id;

    const updated = changeInstrument(score, targetId, "tom_low");

    expect(hitsAt(updated, 1, 2, 0)[0]).toEqual(untouched);
  });
});
