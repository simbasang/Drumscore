import { SyncedPlayer, type AudioContextLike } from "../SyncedPlayer";

class FakeGainNode {
  gain = { value: 1 };
  connect = jest.fn();
}

class FakeBufferSource {
  buffer: unknown = null;
  connect = jest.fn();
  start = jest.fn();
  stop = jest.fn();
}

class FakeAudioContext implements AudioContextLike {
  currentTime = 0;
  destination = {};
  createBufferSource = jest.fn(() => new FakeBufferSource());
  createGain = jest.fn(() => new FakeGainNode());
}

function makeBuffer(duration: number) {
  return { duration };
}

describe("SyncedPlayer", () => {
  let context: FakeAudioContext;

  beforeEach(() => {
    context = new FakeAudioContext();
  });

  it("should report time 0 before playback starts", () => {
    const player = new SyncedPlayer(context, makeBuffer(10), makeBuffer(10));

    expect(player.getCurrentTime()).toBe(0);
  });

  it("should derive current time from the audio context clock, not an independent timer", () => {
    const player = new SyncedPlayer(context, makeBuffer(10), makeBuffer(10));

    context.currentTime = 10;
    player.play();
    context.currentTime = 15;

    expect(player.getCurrentTime()).toBe(5);
  });

  it("should freeze the reported time when paused, even as the context clock keeps advancing", () => {
    const player = new SyncedPlayer(context, makeBuffer(10), makeBuffer(10));

    context.currentTime = 0;
    player.play();
    context.currentTime = 3;
    player.pause();
    context.currentTime = 100;

    expect(player.getCurrentTime()).toBe(3);
  });

  it("should start both stems at the same offset when playing", () => {
    const player = new SyncedPlayer(context, makeBuffer(10), makeBuffer(10));

    player.play();

    const sources = context.createBufferSource.mock.results.map((r) => r.value as FakeBufferSource);
    expect(sources).toHaveLength(2);
    sources.forEach((source) => {
      expect(source.start).toHaveBeenCalledWith(0, 0);
    });
  });

  it("should seek while paused without starting playback", () => {
    const player = new SyncedPlayer(context, makeBuffer(10), makeBuffer(10));

    player.seek(4);

    expect(player.getCurrentTime()).toBe(4);
    expect(context.createBufferSource).not.toHaveBeenCalled();
  });

  it("should seek while playing by restarting both sources at the new offset", () => {
    const player = new SyncedPlayer(context, makeBuffer(10), makeBuffer(10));
    context.currentTime = 0;
    player.play();

    const firstSources = context.createBufferSource.mock.results.map((r) => r.value as FakeBufferSource);

    context.currentTime = 2;
    player.seek(6);

    firstSources.forEach((source) => expect(source.stop).toHaveBeenCalled());
    const allSources = context.createBufferSource.mock.results.map((r) => r.value as FakeBufferSource);
    const newSources = allSources.slice(2);
    expect(newSources).toHaveLength(2);
    newSources.forEach((source) => expect(source.start).toHaveBeenCalledWith(0, 6));

    context.currentTime = 4;
    expect(player.getCurrentTime()).toBe(8);
  });

  it("should clamp seek targets to the track duration", () => {
    const player = new SyncedPlayer(context, makeBuffer(10), makeBuffer(8));

    player.seek(999);

    expect(player.getCurrentTime()).toBe(10);
  });

  it("should report duration as the longer of the two stems", () => {
    const player = new SyncedPlayer(context, makeBuffer(10), makeBuffer(7));

    expect(player.duration).toBe(10);
  });

  it("should set the master gain value", () => {
    const player = new SyncedPlayer(context, makeBuffer(10), makeBuffer(10));

    player.setMasterVolume(0.5);

    expect(player.getMasterVolume()).toBe(0.5);
  });
});
