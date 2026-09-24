import type { Analysis } from "./types";

export type JobStatus =
  | "queued"
  | "downloading"
  | "downloaded"
  | "separating_stems"
  | "stems_separated"
  | "transcribing"
  | "transcribed"
  | "mapping_tempo"
  | "completed"
  | "failed";

export interface JobSummary {
  id: string;
  status: JobStatus;
  attempts: number;
  max_attempts: number;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Project {
  id: string;
  title: string;
  source_url: string;
  created_at: string;
  updated_at: string;
  latest_job: JobSummary | null;
}

export interface ProjectListItem {
  id: string;
  title: string;
  source_url: string;
  updated_at: string;
  latest_job_status: JobStatus | null;
  has_edits: boolean;
}

export interface CreatedProject {
  project: Project;
  job: JobSummary;
}

export interface SavedScore {
  version: number;
  score: unknown;
}

export type Stem = "drums" | "accompaniment";

export class NotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NotFoundError";
  }
}

export class DuplicateProjectError extends Error {
  constructor(
    message: string,
    readonly existingProjectId: string,
  ) {
    super(message);
    this.name = "DuplicateProjectError";
  }
}

export class ScoreConflictError extends Error {
  constructor(
    message: string,
    readonly latestVersion: number | null,
  ) {
    super(message);
    this.name = "ScoreConflictError";
  }
}

const JSON_HEADERS = { "Content-Type": "application/json" };

type ErrorBody = { detail?: string; existing_project_id?: string; latest_version?: number | null };

async function readErrorBody(response: Response): Promise<ErrorBody> {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

async function failure(response: Response): Promise<never> {
  const body = await readErrorBody(response);
  const message = body.detail ?? `Request failed (${response.status})`;
  throw response.status === 404 ? new NotFoundError(message) : new Error(message);
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    return failure(response);
  }
  return response.json();
}

export async function createProject(
  baseUrl: string,
  url: string,
  options: { force?: boolean } = {},
): Promise<CreatedProject> {
  const query = options.force ? "?force=true" : "";
  const response = await fetch(`${baseUrl}/api/projects${query}`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ url }),
  });
  if (response.status === 409) {
    const body = await readErrorBody(response);
    throw new DuplicateProjectError(body.detail ?? "Project already exists", String(body.existing_project_id));
  }
  return parse<CreatedProject>(response);
}

export async function listProjects(baseUrl: string): Promise<ProjectListItem[]> {
  return parse<ProjectListItem[]>(await fetch(`${baseUrl}/api/projects`));
}

export async function getProject(baseUrl: string, id: string): Promise<Project> {
  return parse<Project>(await fetch(`${baseUrl}/api/projects/${id}`));
}

export async function deleteProject(baseUrl: string, id: string): Promise<void> {
  const response = await fetch(`${baseUrl}/api/projects/${id}`, { method: "DELETE" });
  if (!response.ok) {
    await failure(response);
  }
}

export async function retryProject(baseUrl: string, id: string): Promise<JobSummary> {
  return parse<JobSummary>(await fetch(`${baseUrl}/api/projects/${id}/retry`, { method: "POST" }));
}

export async function getAnalysis(baseUrl: string, id: string): Promise<Analysis> {
  return parse<Analysis>(await fetch(`${baseUrl}/api/projects/${id}/analysis`));
}

export async function getSavedScore(baseUrl: string, id: string): Promise<SavedScore | null> {
  const response = await fetch(`${baseUrl}/api/projects/${id}/score`);
  if (response.status === 404) {
    return null;
  }
  return parse<SavedScore>(response);
}

export async function saveScore(
  baseUrl: string,
  id: string,
  score: unknown,
  baseVersion: number | null,
): Promise<number> {
  const response = await fetch(`${baseUrl}/api/projects/${id}/score`, {
    method: "PUT",
    headers: JSON_HEADERS,
    body: JSON.stringify({ score, base_version: baseVersion }),
  });
  if (response.status === 409) {
    const body = await readErrorBody(response);
    throw new ScoreConflictError(
      body.detail ?? "A newer version of this score was saved elsewhere",
      body.latest_version ?? null,
    );
  }
  const body = await parse<{ version: number }>(response);
  return body.version;
}

export function audioUrl(baseUrl: string, id: string, stem: Stem): string {
  return `${baseUrl}/api/projects/${id}/audio/${stem}`;
}
