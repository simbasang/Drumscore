"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { createProject, DuplicateProjectError } from "@/lib/api/projects";

interface NewProjectFormProps {
  apiBaseUrl: string;
}

interface Duplicate {
  url: string;
  existingProjectId: string;
}

export default function NewProjectForm({ apiBaseUrl }: NewProjectFormProps) {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<Duplicate | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(targetUrl: string, force: boolean) {
    setSubmitting(true);
    try {
      const created = await createProject(apiBaseUrl, targetUrl, { force });
      router.push(`/projects/${created.project.id}`);
    } catch (err) {
      if (err instanceof DuplicateProjectError) {
        setDuplicate({ url: targetUrl, existingProjectId: err.existingProjectId });
        setError(null);
      } else {
        setError(err instanceof Error ? err.message : "Failed to create project.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = url.trim();
    setDuplicate(null);
    if (!trimmed) {
      setError("Please enter a YouTube URL.");
      return;
    }
    void submit(trimmed, false);
  }

  return (
    <div style={{ width: "100%" }}>
      <form onSubmit={handleSubmit}>
        <label htmlFor="youtube-url">YouTube URL</label>
        <input id="youtube-url" type="text" value={url} onChange={(event) => setUrl(event.target.value)} />
        <button type="submit" disabled={submitting}>
          Generate drum score
        </button>
      </form>
      {error && <p role="alert">{error}</p>}
      {duplicate && (
        <div role="dialog" aria-label="Song already processed">
          <p>This song already has a project.</p>
          <button type="button" onClick={() => router.push(`/projects/${duplicate.existingProjectId}`)}>
            Open existing
          </button>
          <button type="button" onClick={() => void submit(duplicate.url, true)}>
            Process anyway
          </button>
        </div>
      )}
    </div>
  );
}
