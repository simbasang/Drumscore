"use client";

import { useState } from "react";

import { createJob, type Job } from "@/lib/api/jobs";

interface JobFormProps {
  apiBaseUrl: string;
}

export default function JobForm({ apiBaseUrl }: JobFormProps) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmedUrl = url.trim();
    if (!trimmedUrl) {
      setError("Please enter a YouTube URL.");
      setJob(null);
      return;
    }

    try {
      const createdJob = await createJob(apiBaseUrl, trimmedUrl);
      setJob(createdJob);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create job.");
      setJob(null);
    }
  }

  return (
    <div>
      <form onSubmit={handleSubmit}>
        <label htmlFor="youtube-url">YouTube URL</label>
        <input
          id="youtube-url"
          type="text"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
        />
        <button type="submit">Generate drum score</button>
      </form>
      {error && <p role="alert">{error}</p>}
      {job && (
        <p>
          Job created: {job.id} — status: {job.status}
        </p>
      )}
    </div>
  );
}
