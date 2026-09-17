export type JobStatus = "queued";

export interface Job {
  id: string;
  url: string;
  status: JobStatus;
}

export async function createJob(baseUrl: string, url: string): Promise<Job> {
  const response = await fetch(`${baseUrl}/api/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });

  const body = await response.json();

  if (!response.ok) {
    throw new Error(body.detail ?? "Failed to create job");
  }

  return body;
}
