export interface AudioBufferLike {
  duration: number;
}

export interface GainNodeLike {
  gain: { value: number };
  connect(destination: unknown): void;
}

export interface BufferSourceNodeLike {
  buffer: unknown;
  playbackRate: { value: number };
  connect(destination: unknown): void;
  start(when?: number, offset?: number): void;
  stop(): void;
}

export interface AudioContextLike {
  readonly currentTime: number;
  readonly destination: unknown;
  createBufferSource(): BufferSourceNodeLike;
  createGain(): GainNodeLike;
}

export class SyncedPlayer {
  private readonly context: AudioContextLike;
  private readonly drumsBuffer: AudioBufferLike;
  private readonly accompanimentBuffer: AudioBufferLike;
  private readonly drumsGain: GainNodeLike;
  private readonly accompanimentGain: GainNodeLike;
  private readonly masterGain: GainNodeLike;
  private drumsSource: BufferSourceNodeLike | null = null;
  private accompanimentSource: BufferSourceNodeLike | null = null;
  private startContextTime = 0;
  private offset = 0;
  private playing = false;
  private rate = 1;

  constructor(
    context: AudioContextLike,
    drumsBuffer: AudioBufferLike,
    accompanimentBuffer: AudioBufferLike,
  ) {
    this.context = context;
    this.drumsBuffer = drumsBuffer;
    this.accompanimentBuffer = accompanimentBuffer;

    this.drumsGain = context.createGain();
    this.accompanimentGain = context.createGain();
    this.masterGain = context.createGain();
    this.drumsGain.connect(this.masterGain);
    this.accompanimentGain.connect(this.masterGain);
    this.masterGain.connect(context.destination);
  }

  get duration(): number {
    return Math.max(this.drumsBuffer.duration, this.accompanimentBuffer.duration);
  }

  get isPlaying(): boolean {
    return this.playing;
  }

  play(): void {
    if (this.playing) {
      return;
    }
    this.offset = Math.max(0, Math.min(this.offset, this.duration));
    this.startSources(this.offset);
    this.startContextTime = this.context.currentTime;
    this.playing = true;
  }

  pause(): void {
    if (!this.playing) {
      return;
    }
    this.offset = this.getCurrentTime();
    this.stopSources();
    this.playing = false;
  }

  seek(time: number): void {
    const clamped = Math.max(0, Math.min(time, this.duration));

    if (this.playing) {
      this.stopSources();
      this.offset = clamped;
      this.startSources(this.offset);
      this.startContextTime = this.context.currentTime;
    } else {
      this.offset = clamped;
    }
  }

  getCurrentTime(): number {
    if (!this.playing) {
      return this.offset;
    }
    const elapsed = this.offset + (this.context.currentTime - this.startContextTime) * this.rate;
    if (elapsed >= this.duration) {
      this.stopSources();
      this.playing = false;
      this.offset = this.duration;
      return this.offset;
    }
    return elapsed;
  }

  setPlaybackRate(rate: number): void {
    const currentOffset = this.getCurrentTime();
    if (this.playing) {
      this.stopSources();
      this.rate = rate;
      this.offset = currentOffset;
      this.startSources(this.offset);
      this.startContextTime = this.context.currentTime;
    } else {
      this.rate = rate;
    }
  }

  getPlaybackRate(): number {
    return this.rate;
  }

  setMasterVolume(value: number): void {
    this.masterGain.gain.value = value;
  }

  getMasterVolume(): number {
    return this.masterGain.gain.value;
  }

  setDrumsVolume(value: number): void {
    this.drumsGain.gain.value = value;
  }

  getDrumsVolume(): number {
    return this.drumsGain.gain.value;
  }

  private startSources(offset: number): void {
    this.drumsSource = this.context.createBufferSource();
    this.drumsSource.buffer = this.drumsBuffer;
    this.drumsSource.playbackRate.value = this.rate;
    this.drumsSource.connect(this.drumsGain);
    this.drumsSource.start(0, offset);

    this.accompanimentSource = this.context.createBufferSource();
    this.accompanimentSource.buffer = this.accompanimentBuffer;
    this.accompanimentSource.playbackRate.value = this.rate;
    this.accompanimentSource.connect(this.accompanimentGain);
    this.accompanimentSource.start(0, offset);
  }

  private stopSources(): void {
    this.drumsSource?.stop();
    this.accompanimentSource?.stop();
    this.drumsSource = null;
    this.accompanimentSource = null;
  }
}
