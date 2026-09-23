import type { GainNodeLike } from "./SyncedPlayer";

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

  constructor(player: PlayerLike, context: MetronomeContextLike, _beats: unknown[]) {
    this.player = player;
    this.context = context;
  }

  play(): void {
    this.player.play();
  }

  pause(): void {
    this.player.pause();
  }

  seek(time: number): void {
    this.player.seek(time);
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

  tick(): number {
    const currentTime = this.player.getCurrentTime();
    if (shouldRestartLoop(currentTime, this.loop)) {
      const restartTime = loopRestartOffset(this.loop as LoopRange);
      this.player.seek(restartTime);
      return restartTime;
    }
    return currentTime;
  }
}
