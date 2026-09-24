"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { deleteProject, listProjects, type JobStatus, type ProjectListItem } from "@/lib/api/projects";

interface ProjectLibraryProps {
  apiBaseUrl: string;
}

function statusText(status: JobStatus | null): string {
  if (status === "completed") {
    return "Ready";
  }
  if (status === "failed") {
    return "Failed";
  }
  return status ? "Processing" : "";
}

export default function ProjectLibrary({ apiBaseUrl }: ProjectLibraryProps) {
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listProjects(apiBaseUrl)
      .then((items) => {
        if (!cancelled) {
          setProjects(items);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load projects.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl]);

  async function handleDelete(project: ProjectListItem) {
    if (!window.confirm(`Delete "${project.title}"? This cannot be undone.`)) {
      return;
    }
    try {
      await deleteProject(apiBaseUrl, project.id);
      // The Delete button only renders once `projects` is a non-empty array
      // (see the JSX below), so `current` can never be null here; the
      // fallback only satisfies the setState updater's nullable type.
      setProjects((current) => (current ?? /* istanbul ignore next */ []).filter((p) => p.id !== project.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete project.");
    }
  }

  return (
    <section aria-labelledby="library-heading" style={{ width: "100%" }}>
      <h2 id="library-heading">My projects</h2>
      {error && <p role="alert">{error}</p>}
      {projects === null && !error && <p>Loading projects...</p>}
      {projects?.length === 0 && <p>No projects yet. Submit a YouTube URL to start one.</p>}
      {projects && projects.length > 0 && (
        <ul>
          {projects.map((project) => (
            <li key={project.id}>
              <Link href={`/projects/${project.id}`}>{project.title}</Link>{" "}
              <span>
                {statusText(project.latest_job_status)}
                {project.has_edits && " · edited"}
              </span>{" "}
              <button type="button" aria-label={`Delete ${project.title}`} onClick={() => void handleDelete(project)}>
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
