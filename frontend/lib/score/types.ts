import type { DrumInstrument } from "@/lib/api/types";

export type Provenance = string;

export interface MusicalPosition {
  measure: number;
  beat: number;
  subdivision: number;
}

export interface ScoreHit {
  id: string;
  sourceEventId: string | null;
  time: number | null;
  instrument: DrumInstrument;
  confidence: number | null;
  provenance: Provenance;
}

export interface ScoreNote {
  type: "note";
  id: string;
  position: MusicalPosition;
  duration: string;
  hits: ScoreHit[];
}

export interface ScoreRest {
  type: "rest";
  id: string;
  position: MusicalPosition;
  duration: string;
}

export type Slot = ScoreNote | ScoreRest;
export type Measure = Slot[];

export interface Score {
  measures: Measure[];
}
