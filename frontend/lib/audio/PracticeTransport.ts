import type { GainNodeLike } from "./SyncedPlayer";
import type { Beat } from "@/lib/api/jobs";
import { beatPeriodAt, contextTimeForSourceTime, countInClickTimes } from "./metronomeScheduling";

const METRONOME_LOOKAHEAD_SECONDS = 0.1;
const CLICK_FREQUENCY_DOWNBEAT = 1500;
const CLICK_FREQUENCY_BEAT = 1000;
const CLICK_DURATION_SECONDS = 0.03;
const COUNT_IN_CLICK_COUNT = 4;

export interface LoopRange {
  startTime: number;
  endTime: number;
}

export function shouldRestartLoop(currentTime: number, loop: LoopRange | null): boolean {
  return loop != null && currentTime >= loop.endTime;
}

export function loopRestartOffset(loop: LoopRange): number {
  return loop.startTime;
}

export interface PlayerLike {
  readonly isPlaying: boolean;
  readonly duration: number;
  play(): void;
  pause(): void;
  seek(time: number): void;
  getCurrentTime(): number;
  setPlaybackRate(rate: number): void;
  getPlaybackRate(): number;
  setMasterVolume(value: number): void;
  getMasterVolume(): number;
  setDrumsVolume(value: number): void;
  getDrumsVolume(): number;
}

export interface OscillatorNodeLike {
  frequency: { value: number };
  connect(destination: unknown): void;
  start(when?: number): void;
  stop(when?: number): void;
}

export interface MetronomeContextLike {
  readonly currentTime: number;
  readonly destination: unknown;
  createGain(): GainNodeLike;
  createOscillator(): OscillatorNodeLike;
}

export class PracticeTransport {
  private readonly player: PlayerLike;
  protected readonly context: MetronomeContextLike;
  private loop: LoopRange | null = null;
  private readonly beats: Beat[];
  private metronomeEnabled = false;
  private nextMetronomeBeatIndex = -1;

  constructor(player: PlayerLike, context: MetronomeContextLike, beats: Beat[]) {
    this.player = player;
    this.context = context;
    this.beats = beats;
  }

  play(): void {
    this.player.play();
  }

  pause(): void {
    this.player.pause();
  }

  seek(time: number): void {
    this.player.seek(time);
    if (this.metronomeEnabled) {
      this.nextMetronomeBeatIndex = this.beats.findIndex((beat) => beat.source_time >= time);
    }
  }

  getCurrentTime(): number {
    return this.player.getCurrentTime();
  }

  get isPlaying(): boolean {
    return this.player.isPlaying;
  }

  get duration(): number {
    return this.player.duration;
  }

  setLoop(range: LoopRange | null): void {
    this.loop = range;
  }

  getLoop(): LoopRange | null {
    return this.loop;
  }

  setPlaybackRate(rate: number): void {
    this.player.setPlaybackRate(rate);
  }

  getPlaybackRate(): number {
    return this.player.getPlaybackRate();
  }

  setMasterVolume(value: number): void {
    this.player.setMasterVolume(value);
  }

  getMasterVolume(): number {
    return this.player.getMasterVolume();
  }

  setDrumsVolume(value: number): void {
    this.player.setDrumsVolume(value);
  }

  getDrumsVolume(): number {
    return this.player.getDrumsVolume();
  }

  tick(): number {
    const currentTime = this.player.getCurrentTime();
    let resultTime = currentTime;

    if (shouldRestartLoop(currentTime, this.loop)) {
      const restartTime = loopRestartOffset(this.loop as LoopRange);
      this.player.seek(restartTime);
      resultTime = restartTime;
      if (this.metronomeEnabled) {
        this.nextMetronomeBeatIndex = this.beats.findIndex((beat) => beat.source_time >= resultTime);
      }
    }

    if (this.metronomeEnabled && this.player.isPlaying) {
      this.scheduleUpcomingClicks(resultTime);
    }

    return resultTime;
  }

  setMetronomeEnabled(enabled: boolean): void {
    this.metronomeEnabled = enabled;
    if (enabled) {
      this.nextMetronomeBeatIndex = this.beats.findIndex((beat) => beat.source_time >= this.player.getCurrentTime());
    }
  }

  playWithCountIn(): void {
    const startTime = this.player.getCurrentTime();
    const clickTimes = countInClickTimes(this.beats, startTime, COUNT_IN_CLICK_COUNT);
    if (clickTimes.length === 0) {
      this.play();
      return;
    }

    const contextNow = this.context.currentTime;
    clickTimes.forEach((offset) => {
      this.scheduleClick(contextNow + offset, false);
    });

    const period = beatPeriodAt(this.beats, startTime) ?? 0;
    const totalDuration = (clickTimes.length - 1) * period;
    setTimeout(() => this.play(), totalDuration * 1000);
  }

  private scheduleUpcomingClicks(currentSourceTime: number): void {
    if (this.nextMetronomeBeatIndex === -1) {
      return;
    }
    const rate = this.player.getPlaybackRate();
    const contextNow = this.context.currentTime;
    const lookaheadSourceTime = currentSourceTime + METRONOME_LOOKAHEAD_SECONDS * rate;

    while (
      this.nextMetronomeBeatIndex < this.beats.length &&
      this.beats[this.nextMetronomeBeatIndex].source_time < lookaheadSourceTime
    ) {
      const beat = this.beats[this.nextMetronomeBeatIndex];
      const when = contextTimeForSourceTime(beat.source_time, currentSourceTime, contextNow, rate);
      this.scheduleClick(when, beat.is_downbeat);
      this.nextMetronomeBeatIndex++;
    }
  }

  private scheduleClick(when: number, isDownbeat: boolean): void {
    const oscillator = this.context.createOscillator();
    const gain = this.context.createGain();
    oscillator.frequency.value = isDownbeat ? CLICK_FREQUENCY_DOWNBEAT : CLICK_FREQUENCY_BEAT;
    oscillator.connect(gain);
    gain.connect(this.context.destination);
    gain.gain.value = 0.5;
    oscillator.start(when);
    oscillator.stop(when + CLICK_DURATION_SECONDS);
  }
}
