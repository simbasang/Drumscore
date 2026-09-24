import type { Analysis } from "./types";

export type { Analysis, AnalysisEvent, Beat, DrumInstrument } from "./types";

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
