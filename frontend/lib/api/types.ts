export type DrumInstrument =
  | "kick"
  | "snare"
  | "hihat_closed"
  | "hihat_open"
  | "crash"
  | "ride"
  | "tom_low"
  | "tom_mid"
  | "tom_high";

export interface AnalysisEvent {
  id: string;
  time: number;
  instrument: DrumInstrument;
  confidence: number | null;
  provenance: string | null;
  measure: number | null;
  beat: number | null;
  subdivision: number | null;
}

export interface Beat {
  source_time: number;
  measure: number;
  beat: number;
  is_downbeat: boolean;
  confidence: number | null;
}

export interface Analysis {
  tempo_bpm: number;
  events: AnalysisEvent[];
  beats: Beat[];
}
