export type JobStatus =
  | "queued"
  | "downloading"
  | "downloaded"
  | "separating_stems"
  | "stems_separated"
  | "failed";

export interface Job {
  id: string;
  url: string;
  status: JobStatus;
  audio_path?: string | null;
  drums_path?: string | null;
  accompaniment_path?: string | null;
  error?: string | null;
}

async function parseJobResponse(response: Response): Promise<Job> {
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

  return parseJobResponse(response);
}

export async function getJob(baseUrl: string, id: string): Promise<Job> {
  const response = await fetch(`${baseUrl}/api/jobs/${id}`);

  return parseJobResponse(response);
}
