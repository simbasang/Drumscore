import type { ScoreHit } from "./types";

export const LOW_CONFIDENCE_THRESHOLD = 0.5;

export function isLowConfidence(hit: ScoreHit): boolean {
  return hit.confidence != null && hit.confidence < LOW_CONFIDENCE_THRESHOLD;
}
