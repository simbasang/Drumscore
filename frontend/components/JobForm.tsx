"use client";

import { useEffect, useRef, useState } from "react";

import { createJob, getAnalysis, getJob, type Analysis, type Job, type JobStatus } from "@/lib/api/jobs";
import DrumScore from "@/components/DrumScore";

interface JobFormProps {
  apiBaseUrl: string;
}

const POLL_INTERVAL_MS = 2000;

const TERMINAL_STATUSES: JobStatus[] = ["tempo_mapped", "failed"];

const STATUS_LABELS: Record<JobStatus, string> = {
  queued: "queued",
  downloading: "Downloading audio...",
  downloaded: "Audio downloaded, starting stem separation...",
  separating_stems: "Separating drum stems...",
  stems_separated: "Drums and accompaniment separated, starting transcription...",
  transcribing: "Transcribing drum hits...",
  transcribed: "starting tempo estimation...",
  mapping_tempo: "Estimating tempo...",
  tempo_mapped: "Done.",
  failed: "Failed.",
};

function statusLabel(job: Job): string {
  if (job.status === "tempo_mapped") {
    const bpm = job.tempo_bpm != null ? Math.round(job.tempo_bpm) : "?";
    return `Done — ${job.event_count ?? 0} drum hits detected at ${bpm} BPM.`;
  }
  if (job.status === "transcribed") {
    return `Done — ${job.event_count ?? 0} drum hits detected, ${STATUS_LABELS.transcribed}`;
  }
  return STATUS_LABELS[job.status];
}

export default function JobForm({ apiBaseUrl }: JobFormProps) {
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
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

  async function fetchAnalysisIfReady(jobId: string, status: JobStatus) {
    if (status !== "tempo_mapped") {
      return;
    }
    try {
      const result = await getAnalysis(apiBaseUrl, jobId);
      setAnalysis(result);
    } catch {
      // Analysis is a bonus once the job is done; a failure here doesn't change job status.
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
        await fetchAnalysisIfReady(jobId, updated.status);
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
      setAnalysis(null);
      if (!TERMINAL_STATUSES.includes(createdJob.status)) {
        startPolling(createdJob.id);
      }
      await fetchAnalysisIfReady(createdJob.id, createdJob.status);
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
          Job created: {job.id} — status: {statusLabel(job)}
        </p>
      )}
      {analysis && <DrumScore events={analysis.events} />}
    </div>
  );
}
