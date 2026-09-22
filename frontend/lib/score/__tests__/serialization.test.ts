import { fromAnalysisEvents } from "../buildScore";
import { fromJSON, toJSON } from "../serialization";
import { addHit } from "../transformations";

describe("toJSON / fromJSON", () => {
  it("should round-trip a freshly constructed score", () => {
    const score = fromAnalysisEvents([
      {
        id: "e",
        time: 0.5,
        instrument: "kick",
        confidence: 0.9,
        provenance: "drumscript",
        measure: 1,
        beat: 1,
        subdivision: 0,
      },
    ]);

    const roundTripped = fromJSON(toJSON(score));

    expect(roundTripped).toEqual(score);
  });

  it("should round-trip a score that has been through a transformation", () => {
    const score = fromAnalysisEvents([
      {
        id: "e",
        time: 0.5,
        instrument: "kick",
        confidence: 0.9,
        provenance: "drumscript",
        measure: 1,
        beat: 1,
        subdivision: 0,
      },
    ]);
    const edited = addHit(score, { measure: 1, beat: 2, subdivision: 0 }, "snare");

    const roundTripped = fromJSON(toJSON(edited));

    expect(roundTripped).toEqual(edited);
  });

  it("should reject JSON that has no measures array", () => {
    expect(() => fromJSON({})).toThrow("Invalid score JSON");
  });
});
