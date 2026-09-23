"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";

import type { AnalysisEvent, Beat, DrumInstrument } from "@/lib/api/jobs";
import { type DecodableAudioContext, loadAudioBuffer } from "@/lib/audio/loadAudioBuffer";
import { PracticeTransport, type MetronomeContextLike } from "@/lib/audio/PracticeTransport";
import { SyncedPlayer } from "@/lib/audio/SyncedPlayer";
import { INSTRUMENT_NOTATION } from "@/lib/notation/instrumentNotation";
import { useScoreEditor } from "@/lib/score/useScoreEditor";
import type { Score } from "@/lib/score/types";

const DrumScore = dynamic(() => import("@/components/DrumScore"), { ssr: false });

interface PlayerProps {
  apiBaseUrl: string;
  jobId: string;
  events: AnalysisEvent[];
  beats?: Beat[];
  createAudioContext?: () => DecodableAudioContext;
}

type LoadStatus = "loading" | "ready" | "error";

const INSTRUMENTS = Object.keys(INSTRUMENT_NOTATION) as DrumInstrument[];
const PLAYBACK_RATES = [0.5, 0.75, 1, 1.25, 1.5];

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

function collectHits(score: Score): { id: string; label: string }[] {
  const result: { id: string; label: string }[] = [];
  score.measures.forEach((measure, measureIndex) => {
    measure.forEach((slot) => {
      if (slot.type !== "note") {
        return;
      }
      slot.hits.forEach((hit) => {
        result.push({
          id: hit.id,
          label: `${hit.instrument} @ m${measureIndex + 1} b${slot.position.beat}.${slot.position.subdivision}`,
        });
      });
    });
  });
  return result;
}

export default function Player({
  apiBaseUrl,
  jobId,
  events,
  beats = [],
  createAudioContext = defaultCreateAudioContext,
}: PlayerProps) {
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [masterVolume, setMasterVolume] = useState(1);
  const [drumsVolume, setDrumsVolume] = useState(1);
  const [loopStart, setLoopStart] = useState<number | null>(null);
  const [loop, setLoop] = useState<{ startTime: number; endTime: number } | null>(null);
  const [playbackRate, setPlaybackRateValue] = useState(1);
  const [metronomeEnabled, setMetronomeEnabled] = useState(false);
  const [selectedHitId, setSelectedHitId] = useState("");
  const [editInstrument, setEditInstrument] = useState<DrumInstrument>(INSTRUMENTS[0]);
  const [movePosition, setMovePosition] = useState({ measure: 1, beat: 1, subdivision: 0 });
  const [addPosition, setAddPosition] = useState({ measure: 1, beat: 1, subdivision: 0 });
  const [addInstrument, setAddInstrument] = useState<DrumInstrument>(INSTRUMENTS[0]);

  const transportRef = useRef<PracticeTransport | null>(null);
  const rafRef = useRef<number | null>(null);
  const contextRef = useRef<DecodableAudioContext | null>(null);
  const countInPendingRef = useRef(false);

  const editor = useScoreEditor(events);
  const hits = collectHits(editor.score);

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
        transportRef.current = new PracticeTransport(player, context as unknown as MetronomeContextLike, beats);
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
      transportRef.current?.pause();
      contextRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBaseUrl, jobId]);

  function tick() {
    const transport = transportRef.current;
    if (!transport) {
      return;
    }
    setCurrentTime(transport.tick());
    if (transport.isPlaying) {
      countInPendingRef.current = false;
      rafRef.current = requestAnimationFrame(tick);
    } else if (countInPendingRef.current) {
      rafRef.current = requestAnimationFrame(tick);
    } else {
      setIsPlaying(false);
    }
  }

  function handlePlayPause() {
    const transport = transportRef.current;
    if (!transport) {
      return;
    }

    if (transport.isPlaying) {
      transport.pause();
      setIsPlaying(false);
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current);
      }
    } else {
      transport.play();
      setIsPlaying(true);
      rafRef.current = requestAnimationFrame(tick);
    }
  }

  function handleCountInPlay() {
    const transport = transportRef.current;
    if (!transport) {
      return;
    }
    countInPendingRef.current = true;
    transport.playWithCountIn();
    setIsPlaying(true);
    rafRef.current = requestAnimationFrame(tick);
  }

  const seekTo = useCallback((time: number) => {
    const transport = transportRef.current;
    if (!transport) {
      return;
    }
    transport.seek(time);
    setCurrentTime(transport.getCurrentTime());
  }, []);

  function handleSeekSlider(event: React.ChangeEvent<HTMLInputElement>) {
    seekTo(Number(event.target.value));
  }

  function handleVolumeChange(event: React.ChangeEvent<HTMLInputElement>) {
    const transport = transportRef.current;
    if (!transport) {
      return;
    }
    const value = Number(event.target.value) / 100;
    transport.setMasterVolume(value);
    setMasterVolume(value);
  }

  function handleDrumsVolumeChange(event: React.ChangeEvent<HTMLInputElement>) {
    const transport = transportRef.current;
    if (!transport) {
      return;
    }
    const value = Number(event.target.value) / 100;
    transport.setDrumsVolume(value);
    setDrumsVolume(value);
  }

  function handleSetLoopStart() {
    setLoopStart(currentTime);
  }

  function handleSetLoopEnd() {
    if (loopStart == null) {
      return;
    }
    const range = { startTime: Math.min(loopStart, currentTime), endTime: Math.max(loopStart, currentTime) };
    setLoop(range);
    transportRef.current?.setLoop(range);
  }

  function handleClearLoop() {
    setLoop(null);
    setLoopStart(null);
    transportRef.current?.setLoop(null);
  }

  function handleRateChange(event: React.ChangeEvent<HTMLSelectElement>) {
    const rate = Number(event.target.value);
    transportRef.current?.setPlaybackRate(rate);
    setPlaybackRateValue(rate);
  }

  function handleMetronomeToggle(event: React.ChangeEvent<HTMLInputElement>) {
    const enabled = event.target.checked;
    transportRef.current?.setMetronomeEnabled(enabled);
    setMetronomeEnabled(enabled);
  }

  function handleDeleteHit() {
    if (!selectedHitId) {
      return;
    }
    editor.deleteHit(selectedHitId);
    setSelectedHitId("");
  }

  function handleChangeInstrument() {
    if (!selectedHitId) {
      return;
    }
    editor.changeInstrument(selectedHitId, editInstrument);
  }

  function handleMoveHit() {
    if (!selectedHitId) {
      return;
    }
    editor.moveHit(selectedHitId, movePosition);
  }

  function handleAddHit() {
    editor.addHit(addPosition, addInstrument);
  }

  if (status === "loading") {
    return <p>Loading audio...</p>;
  }

  if (status === "error") {
    return <p role="alert">Failed to load audio for playback.</p>;
  }

  const measureCount = Math.max(editor.score.measures.length, 1);

  return (
    <div>
      <div>
        <button type="button" onClick={handlePlayPause}>
          {isPlaying ? "Pause" : "Play"}
        </button>
        <button type="button" onClick={handleCountInPlay}>
          Count-in
        </button>
        <input
          type="range"
          aria-label="Seek"
          min={0}
          max={duration}
          step={0.01}
          value={currentTime}
          onChange={handleSeekSlider}
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
        <label>
          Playback speed
          <select aria-label="Playback speed" value={playbackRate} onChange={handleRateChange}>
            {PLAYBACK_RATES.map((rate) => (
              <option key={rate} value={rate}>
                {rate}x
              </option>
            ))}
          </select>
        </label>
        <label>
          <input type="checkbox" aria-label="Metronome" checked={metronomeEnabled} onChange={handleMetronomeToggle} />
          Metronome
        </label>
      </div>
      <div>
        <button type="button" onClick={handleSetLoopStart}>
          Set loop start
        </button>
        <button type="button" onClick={handleSetLoopEnd} disabled={loopStart == null}>
          Set loop end
        </button>
        {loop && (
          <button type="button" onClick={handleClearLoop}>
            Clear loop
          </button>
        )}
      </div>
      <div>
        <label>
          Hit to edit
          <select
            aria-label="Select hit to edit"
            value={selectedHitId}
            onChange={(event) => setSelectedHitId(event.target.value)}
          >
            <option value="">-- none --</option>
            {hits.map((hit) => (
              <option key={hit.id} value={hit.id}>
                {hit.label}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={handleDeleteHit} disabled={!selectedHitId}>
          Delete hit
        </button>
        <label>
          New instrument
          <select
            aria-label="New instrument"
            value={editInstrument}
            onChange={(event) => setEditInstrument(event.target.value as DrumInstrument)}
          >
            {INSTRUMENTS.map((instrument) => (
              <option key={instrument} value={instrument}>
                {instrument}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={handleChangeInstrument} disabled={!selectedHitId}>
          Change instrument
        </button>
        <label>
          Move to measure
          <input
            type="number"
            aria-label="Move to measure"
            min={1}
            max={measureCount}
            value={movePosition.measure}
            onChange={(event) => setMovePosition((p) => ({ ...p, measure: Number(event.target.value) }))}
          />
        </label>
        <label>
          Move to beat
          <input
            type="number"
            aria-label="Move to beat"
            min={1}
            max={4}
            value={movePosition.beat}
            onChange={(event) => setMovePosition((p) => ({ ...p, beat: Number(event.target.value) }))}
          />
        </label>
        <label>
          Move to subdivision
          <input
            type="number"
            aria-label="Move to subdivision"
            min={0}
            max={3}
            value={movePosition.subdivision}
            onChange={(event) => setMovePosition((p) => ({ ...p, subdivision: Number(event.target.value) }))}
          />
        </label>
        <button type="button" onClick={handleMoveHit} disabled={!selectedHitId}>
          Move hit
        </button>
      </div>
      <div>
        <label>
          Add hit instrument
          <select
            aria-label="Add hit instrument"
            value={addInstrument}
            onChange={(event) => setAddInstrument(event.target.value as DrumInstrument)}
          >
            {INSTRUMENTS.map((instrument) => (
              <option key={instrument} value={instrument}>
                {instrument}
              </option>
            ))}
          </select>
        </label>
        <label>
          Add at measure
          <input
            type="number"
            aria-label="Add at measure"
            min={1}
            max={measureCount}
            value={addPosition.measure}
            onChange={(event) => setAddPosition((p) => ({ ...p, measure: Number(event.target.value) }))}
          />
        </label>
        <label>
          Add at beat
          <input
            type="number"
            aria-label="Add at beat"
            min={1}
            max={4}
            value={addPosition.beat}
            onChange={(event) => setAddPosition((p) => ({ ...p, beat: Number(event.target.value) }))}
          />
        </label>
        <label>
          Add at subdivision
          <input
            type="number"
            aria-label="Add at subdivision"
            min={0}
            max={3}
            value={addPosition.subdivision}
            onChange={(event) => setAddPosition((p) => ({ ...p, subdivision: Number(event.target.value) }))}
          />
        </label>
        <button type="button" onClick={handleAddHit}>
          Add hit
        </button>
      </div>
      <div>
        <button type="button" onClick={editor.undo} disabled={!editor.canUndo}>
          Undo
        </button>
        <button type="button" onClick={editor.redo} disabled={!editor.canRedo}>
          Redo
        </button>
      </div>
      <DrumScore score={editor.score} currentTime={currentTime} onSeek={seekTo} />
    </div>
  );
}
