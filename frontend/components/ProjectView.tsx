"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import Player from "@/components/Player";
import {
  getAnalysis,
  getProject,
  getSavedScore,
  NotFoundError,
  retryProject,
  saveScore,
  type JobStatus,
  type Project,
} from "@/lib/api/projects";
import type { Analysis } from "@/lib/api/types";
import { fromJSON, toJSON } from "@/lib/score/serialization";
import type { Score } from "@/lib/score/types";

interface ProjectViewProps {
  apiBaseUrl: string;
  projectId: string;
}

const POLL_INTERVAL_MS = 2000;
const MAX_CONSECUTIVE_POLL_FAILURES = 3;

const STATUS_LABELS: Record<JobStatus, string> = {
  queued: "Queued, waiting for a worker...",
  downloading: "Downloading audio...",
  downloaded: "Audio downloaded, starting stem separation...",
  separating_stems: "Separating drum stems...",
  stems_separated: "Stems separated, starting transcription...",
  transcribing: "Transcribing drum hits...",
  transcribed: "Drum hits transcribed, starting tempo mapping...",
  mapping_tempo: "Mapping tempo and beats...",
  completed: "Done.",
  failed: "Failed.",
};

interface LoadedProject {
  analysis: Analysis;
  initialScore: Score | null;
}

export default function ProjectView({ apiBaseUrl, projectId }: ProjectViewProps) {
  const [project, setProject] = useState<Project | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [connectionIssue, setConnectionIssue] = useState(false);
  const [pollingGaveUp, setPollingGaveUp] = useState(false);
  const [loaded, setLoaded] = useState<LoadedProject | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pollGeneration, setPollGeneration] = useState(0);
  const versionRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    let failures = 0;
    let handle: ReturnType<typeof setTimeout> | null = null;

    async function loadResult() {
      try {
        const [analysis, saved] = await Promise.all([
          getAnalysis(apiBaseUrl, projectId),
          getSavedScore(apiBaseUrl, projectId),
        ]);
        if (cancelled) {
          return;
        }
        versionRef.current = saved?.version ?? null;
        setLoaded({ analysis, initialScore: saved ? fromJSON(saved.score) : null });
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load project.");
        }
      }
    }

    async function poll() {
      try {
        const current = await getProject(apiBaseUrl, projectId);
        if (cancelled) {
          return;
        }
        failures = 0;
        setConnectionIssue(false);
        setProject(current);
        const status = current.latest_job?.status;
        if (status === "completed") {
          await loadResult();
          return;
        }
        if (status === "failed") {
          return;
        }
      } catch (err) {
        if (cancelled) {
          return;
        }
        if (err instanceof NotFoundError) {
          setNotFound(true);
          return;
        }
        failures += 1;
        console.error(`[ProjectView] poll ${failures}/${MAX_CONSECUTIVE_POLL_FAILURES} failed for project ${projectId}:`, err);
        if (failures >= MAX_CONSECUTIVE_POLL_FAILURES) {
          setConnectionIssue(false);
          setPollingGaveUp(true);
          return;
        }
        setConnectionIssue(true);
      }
      handle = setTimeout(poll, POLL_INTERVAL_MS);
    }

    void poll();

    return () => {
      cancelled = true;
      if (handle) {
        clearTimeout(handle);
      }
    };
  }, [apiBaseUrl, projectId, pollGeneration]);

  const handleSave = useCallback(
    async (score: Score) => {
      versionRef.current = await saveScore(apiBaseUrl, projectId, toJSON(score), versionRef.current);
    },
    [apiBaseUrl, projectId],
  );

  async function handleRetry() {
    try {
      await retryProject(apiBaseUrl, projectId);
      setError(null);
      setPollGeneration((generation) => generation + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Retry failed.");
    }
  }

  if (notFound) {
    return <p role="alert">Project not found. It may have been deleted.</p>;
  }

  const job = project?.latest_job ?? null;

  return (
    <div style={{ width: "100%" }}>
      {project ? <h2>{project.title}</h2> : <p>Loading project...</p>}
      {connectionIssue && <p>Lost connection, retrying...</p>}
      {pollingGaveUp && (
        <p role="alert">Lost connection to the server. Status may be out of date — reload the page to check again.</p>
      )}
      {job?.status === "failed" && (
        <div>
          <p role="alert">{job.error ?? STATUS_LABELS.failed}</p>
          <button type="button" onClick={() => void handleRetry()}>
            Retry processing
          </button>
        </div>
      )}
      {job && job.status !== "failed" && !loaded && <p>{STATUS_LABELS[job.status]}</p>}
      {error && <p role="alert">{error}</p>}
      {loaded && (
        <Player
          apiBaseUrl={apiBaseUrl}
          projectId={projectId}
          events={loaded.analysis.events}
          beats={loaded.analysis.beats}
          initialScore={loaded.initialScore}
          onSave={handleSave}
        />
      )}
    </div>
  );
}
