"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

import type { AnalysisEvent } from "@/lib/api/jobs";
import { type DecodableAudioContext, loadAudioBuffer } from "@/lib/audio/loadAudioBuffer";
import { SyncedPlayer } from "@/lib/audio/SyncedPlayer";

// VexFlow (imported by DrumScore) is the single largest chunk in the app's
// JS bundle. It's only needed once a job reaches tempo_mapped, often
// minutes after the page first loads, so it's loaded on demand instead of
// bundled into the initial page load.
const DrumScore = dynamic(() => import("@/components/DrumScore"), { ssr: false });

interface PlayerProps {
  apiBaseUrl: string;
  jobId: string;
  events: AnalysisEvent[];
  createAudioContext?: () => DecodableAudioContext;
}

type LoadStatus = "loading" | "ready" | "error";

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "0:00";
  }
  const totalSeconds = Math.floor(seconds);
  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
}

function defaultCreateAudioContext(): DecodableAudioContext {
  return new AudioContext() as unknown as DecodableAudioContext;
}

export default function Player({
  apiBaseUrl,
  jobId,
  events,
  createAudioContext = defaultCreateAudioContext,
}: PlayerProps) {
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [masterVolume, setMasterVolume] = useState(1);
  const [drumsVolume, setDrumsVolume] = useState(1);
  const playerRef = useRef<SyncedPlayer | null>(null);
  const rafRef = useRef<number | null>(null);
  const contextRef = useRef<DecodableAudioContext | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const context = createAudioContext();
        contextRef.current = context;
        const [drumsBuffer, accompanimentBuffer] = await Promise.all([
          loadAudioBuffer(`${apiBaseUrl}/api/jobs/${jobId}/audio/drums`, context),
          loadAudioBuffer(`${apiBaseUrl}/api/jobs/${jobId}/audio/accompaniment`, context),
        ]);

        if (cancelled) {
          return;
        }

        const player = new SyncedPlayer(context, drumsBuffer, accompanimentBuffer);
        playerRef.current = player;
        setDuration(player.duration);
        setStatus("ready");
      } catch (error) {
        if (!cancelled) {
          console.error(`[Player] failed to load audio for job ${jobId}:`, error);
          setStatus("error");
        }
      }
    }

    load();

    return () => {
      cancelled = true;
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
      }
      playerRef.current?.pause();
      contextRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBaseUrl, jobId]);

  function tick() {
    // playerRef.current is only ever null before status becomes "ready", at
    // which point none of tick/handlePlayPause/handleSeek/handleVolumeChange/
    // handleDrumsVolumeChange can be invoked yet (their controls aren't
    // rendered). Kept as a defensive type narrowing, not reachable via the UI.
    const player = playerRef.current;
    if (!player) {
      return;
    }
    setCurrentTime(player.getCurrentTime());
    if (player.isPlaying) {
      rafRef.current = requestAnimationFrame(tick);
    } else {
      setIsPlaying(false);
    }
  }

  function handlePlayPause() {
    const player = playerRef.current;
    if (!player) {
      return;
    }

    if (player.isPlaying) {
      player.pause();
      setIsPlaying(false);
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
      }
    } else {
      player.play();
      setIsPlaying(true);
      rafRef.current = requestAnimationFrame(tick);
    }
  }

  function handleSeek(event: React.ChangeEvent<HTMLInputElement>) {
    const player = playerRef.current;
    if (!player) {
      return;
    }
    const time = Number(event.target.value);
    player.seek(time);
    setCurrentTime(player.getCurrentTime());
  }

  function handleVolumeChange(event: React.ChangeEvent<HTMLInputElement>) {
    const player = playerRef.current;
    if (!player) {
      return;
    }
    const value = Number(event.target.value) / 100;
    player.setMasterVolume(value);
    setMasterVolume(value);
  }

  function handleDrumsVolumeChange(event: React.ChangeEvent<HTMLInputElement>) {
    const player = playerRef.current;
    if (!player) {
      return;
    }
    const value = Number(event.target.value) / 100;
    player.setDrumsVolume(value);
    setDrumsVolume(value);
  }

  if (status === "loading") {
    return <p>Loading audio...</p>;
  }

  if (status === "error") {
    return <p role="alert">Failed to load audio for playback.</p>;
  }

  return (
    <div>
      <div>
        <button type="button" onClick={handlePlayPause}>
          {isPlaying ? "Pause" : "Play"}
        </button>
        <input
          type="range"
          aria-label="Seek"
          min={0}
          max={duration}
          step={0.01}
          value={currentTime}
          onChange={handleSeek}
        />
        <span>
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>
        <label>
          Master volume
          <input
            type="range"
            aria-label="Master volume"
            min={0}
            max={100}
            value={masterVolume * 100}
            onChange={handleVolumeChange}
          />
        </label>
        <label>
          Drums volume
          <input
            type="range"
            aria-label="Drums volume"
            min={0}
            max={100}
            value={drumsVolume * 100}
            onChange={handleDrumsVolumeChange}
          />
        </label>
      </div>
      <DrumScore events={events} currentTime={currentTime} />
    </div>
  );
}
