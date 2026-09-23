import {
  loopRestartOffset,
  PracticeTransport,
  shouldRestartLoop,
  type MetronomeContextLike,
  type PlayerLike,
} from "../PracticeTransport";

class FakePlayer implements PlayerLike {
  isPlaying = false;
  duration = 30;
  play = jest.fn(() => {
    this.isPlaying = true;
  });
  pause = jest.fn(() => {
    this.isPlaying = false;
  });
  seek = jest.fn();
  getCurrentTime = jest.fn(() => 0);
  setPlaybackRate = jest.fn();
  getPlaybackRate = jest.fn(() => 1);
}

function fakeContext(): MetronomeContextLike {
  return {
    currentTime: 0,
    destination: {},
    createGain: jest.fn(() => ({ gain: { value: 1 }, connect: jest.fn() })),
    createOscillator: jest.fn(() => ({
      frequency: { value: 0 },
      connect: jest.fn(),
      start: jest.fn(),
      stop: jest.fn(),
    })),
  };
}

describe("shouldRestartLoop", () => {
  it("should return false when there is no loop", () => {
    expect(shouldRestartLoop(5, null)).toBe(false);
  });

  it("should return false while current time is before the loop end", () => {
    expect(shouldRestartLoop(5, { startTime: 1, endTime: 10 })).toBe(false);
  });

  it("should return true once current time reaches the loop end", () => {
    expect(shouldRestartLoop(10, { startTime: 1, endTime: 10 })).toBe(true);
  });
});

describe("loopRestartOffset", () => {
  it("should return the loop's start time", () => {
    expect(loopRestartOffset({ startTime: 3, endTime: 10 })).toBe(3);
  });
});

describe("PracticeTransport", () => {
  let player: FakePlayer;
  let transport: PracticeTransport;

  beforeEach(() => {
    player = new FakePlayer();
    transport = new PracticeTransport(player, fakeContext(), []);
  });

  it("should delegate play/pause/seek to the wrapped player", () => {
    transport.play();
    transport.seek(4);
    transport.pause();

    expect(player.play).toHaveBeenCalled();
    expect(player.seek).toHaveBeenCalledWith(4);
    expect(player.pause).toHaveBeenCalled();
  });

  it("should delegate getCurrentTime, isPlaying, and duration to the wrapped player", () => {
    player.getCurrentTime.mockReturnValue(9);
    player.isPlaying = true;

    expect(transport.getCurrentTime()).toBe(9);
    expect(transport.isPlaying).toBe(true);
    expect(transport.duration).toBe(30);
  });

  it("should return the wrapped player's current time from tick when no loop is set", () => {
    player.getCurrentTime.mockReturnValue(7);

    expect(transport.tick()).toBe(7);
    expect(player.seek).not.toHaveBeenCalled();
  });

  it("should seek back to the loop start and report the restarted time once playback crosses the loop end", () => {
    transport.setLoop({ startTime: 2, endTime: 8 });
    player.getCurrentTime.mockReturnValue(8);

    const result = transport.tick();

    expect(player.seek).toHaveBeenCalledWith(2);
    expect(result).toBe(2);
  });

  it("should clear the loop when set to null", () => {
    transport.setLoop({ startTime: 2, endTime: 8 });
    transport.setLoop(null);
    player.getCurrentTime.mockReturnValue(8);

    transport.tick();

    expect(player.seek).not.toHaveBeenCalled();
  });

  it("should report the currently set loop range", () => {
    const range = { startTime: 1, endTime: 5 };
    transport.setLoop(range);

    expect(transport.getLoop()).toEqual(range);
  });

  it("should delegate playback rate get/set to the wrapped player", () => {
    transport.setPlaybackRate(1.5);
    player.getPlaybackRate.mockReturnValue(1.5);

    expect(player.setPlaybackRate).toHaveBeenCalledWith(1.5);
    expect(transport.getPlaybackRate()).toBe(1.5);
  });
});
