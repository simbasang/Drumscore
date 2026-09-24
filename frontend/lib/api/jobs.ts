export type JobStatus =
  | "queued"
  | "downloading"
  | "downloaded"
  | "separating_stems"
  | "stems_separated"
  | "transcribing"
  | "transcribed"
  | "mapping_tempo"
  | "tempo_mapped"
  | "failed";

export interface Job {
  id: string;
  url: string;
  status: JobStatus;
  audio_path?: string | null;
  drums_path?: string | null;
  accompaniment_path?: string | null;
  event_count?: number | null;
  tempo_bpm?: number | null;
  error?: string | null;
}

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

async function parseResponse<T>(response: Response): Promise<T> {
  const body = await response.json();

  if (!response.ok) {
    throw new Error(body.detail ?? "Request failed");
  }

  return body;
}

export async function createJob(baseUrl: string, url: string): Promise<Job> {
  const response = await fetch(`${baseUrl}/api/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });

  return parseResponse<Job>(response);
}

export async function getJob(baseUrl: string, id: string): Promise<Job> {
  const response = await fetch(`${baseUrl}/api/jobs/${id}`);

  return parseResponse<Job>(response);
}

export async function getAnalysis(baseUrl: string, id: string): Promise<Analysis> {
  const response = await fetch(`${baseUrl}/api/jobs/${id}/analysis`);

  return parseResponse<Analysis>(response);
}
