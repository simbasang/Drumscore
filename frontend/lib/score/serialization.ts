import type { Score } from "./types";

export function toJSON(score: Score): unknown {
  return JSON.parse(JSON.stringify(score));
}

export function fromJSON(json: unknown): Score {
  if (typeof json !== "object" || json === null || !Array.isArray((json as { measures?: unknown }).measures)) {
    throw new Error("Invalid score JSON: expected an object with a measures array");
  }
  return json as Score;
}
