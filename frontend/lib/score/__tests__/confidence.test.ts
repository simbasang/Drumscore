import { isLowConfidence, LOW_CONFIDENCE_THRESHOLD } from "../confidence";
import type { ScoreHit } from "../types";

function hit(overrides: Partial<ScoreHit>): ScoreHit {
  return {
    id: "h",
    sourceEventId: "e",
    time: 0,
    instrument: "kick",
    confidence: null,
    provenance: "drumscript",
    ...overrides,
  };
}

describe("isLowConfidence", () => {
  it("should return false when confidence is null", () => {
    expect(isLowConfidence(hit({ confidence: null }))).toBe(false);
  });

  it("should return false when confidence is at or above the threshold", () => {
    expect(isLowConfidence(hit({ confidence: LOW_CONFIDENCE_THRESHOLD }))).toBe(false);
    expect(isLowConfidence(hit({ confidence: 0.9 }))).toBe(false);
  });

  it("should return true when confidence is below the threshold", () => {
    expect(isLowConfidence(hit({ confidence: 0.2 }))).toBe(true);
  });
});
