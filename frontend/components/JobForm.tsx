"use client";

import { useEffect, useRef, useState } from "react";

import { createJob, getJob, type Job, type JobStatus } from "@/lib/api/jobs";

interface JobFormProps {
  apiBaseUrl: string;
}

const POLL_INTERVAL_MS = 2000;

const TERMINAL_STATUSES: JobStatus[] = ["stems_separated", "failed"];

const STATUS_LABELS: Record<JobStatus, string> = {
  queued: "queued",
  downloading: "Downloading audio...",
  downloaded: "Audio downloaded, starting stem separation...",
  separating_stems: "Separating drum stems...",
  stems_separated: "Done — drums and accompaniment separated.",
  failed: "Failed.",
};

export default function JobForm({ apiBaseUrl }: JobFormProps) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const pollHandle = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (pollHandle.current) {
        clearInterval(pollHandle.current);
      }
    };
  }, []);

  function stopPolling() {
    if (pollHandle.current) {
      clearInterval(pollHandle.current);
      pollHandle.current = null;
    }
  }

  function startPolling(jobId: string) {
    stopPolling();
    pollHandle.current = setInterval(async () => {
      try {
        const updated = await getJob(apiBaseUrl, jobId);
        setJob(updated);
        if (TERMINAL_STATUSES.includes(updated.status)) {
          stopPolling();
        }
      } catch {
        stopPolling();
      }
    }, POLL_INTERVAL_MS);
  }

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
      if (!TERMINAL_STATUSES.includes(createdJob.status)) {
        startPolling(createdJob.id);
      }
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
      {job && job.status === "failed" && (
        <p role="alert">{job.error ?? STATUS_LABELS.failed}</p>
      )}
      {job && job.status !== "failed" && (
        <p>
          Job created: {job.id} — status: {STATUS_LABELS[job.status]}
        </p>
      )}
    </div>
  );
}
