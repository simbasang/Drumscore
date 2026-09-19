import { loadAudioBuffer, type DecodableAudioContext } from "../loadAudioBuffer";

function fakeContext(decodeAudioData: jest.Mock): DecodableAudioContext {
  return {
    currentTime: 0,
    destination: {},
    createBufferSource: jest.fn(),
    createGain: jest.fn(),
    decodeAudioData,
  } as unknown as DecodableAudioContext;
}

function noopSleep() {
  return Promise.resolve();
}

describe("loadAudioBuffer", () => {
  let consoleErrorSpy: jest.SpyInstance;

  beforeEach(() => {
    consoleErrorSpy = jest.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    consoleErrorSpy.mockRestore();
  });

  it("should fetch and decode audio data from the given URL", async () => {
    const arrayBuffer = new ArrayBuffer(8);
    const decodedBuffer = { duration: 12.5 };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      arrayBuffer: () => Promise.resolve(arrayBuffer),
    } as unknown as Response);
    const decodeAudioData = jest.fn().mockResolvedValue(decodedBuffer);
    const context = fakeContext(decodeAudioData);

    const result = await loadAudioBuffer("http://localhost:8000/audio.wav", context);

    expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/audio.wav");
    expect(decodeAudioData).toHaveBeenCalledWith(arrayBuffer);
    expect(result).toBe(decodedBuffer);
    expect(consoleErrorSpy).not.toHaveBeenCalled();
  });

  it("should retry after a transient failure and succeed without exhausting attempts", async () => {
    const arrayBuffer = new ArrayBuffer(8);
    const decodedBuffer = { duration: 12.5 };
    global.fetch = jest
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        arrayBuffer: () => Promise.resolve(arrayBuffer),
      } as unknown as Response);
    const decodeAudioData = jest.fn().mockResolvedValue(decodedBuffer);
    const context = fakeContext(decodeAudioData);

    const result = await loadAudioBuffer("http://localhost:8000/audio.wav", context, {
      sleep: noopSleep,
    });

    expect(global.fetch).toHaveBeenCalledTimes(2);
    expect(result).toBe(decodedBuffer);
    expect(consoleErrorSpy).toHaveBeenCalledTimes(1);
    expect(consoleErrorSpy.mock.calls[0][0]).toContain("attempt 1/3");
  });

  it("should retry the configured number of attempts then throw the last error", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 500 } as Response);
    const decodeAudioData = jest.fn();
    const context = fakeContext(decodeAudioData);

    await expect(
      loadAudioBuffer("http://localhost:8000/audio.wav", context, {
        attempts: 3,
        sleep: noopSleep,
      }),
    ).rejects.toThrow("Failed to load audio");

    expect(global.fetch).toHaveBeenCalledTimes(3);
    expect(decodeAudioData).not.toHaveBeenCalled();
    expect(consoleErrorSpy).toHaveBeenCalledTimes(3);
    expect(consoleErrorSpy.mock.calls[2][0]).toContain("attempt 3/3");
  });

  it("should use exponential backoff delays between attempts", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 500 } as Response);
    const sleep = jest.fn().mockResolvedValue(undefined);

    await expect(
      loadAudioBuffer("http://localhost:8000/audio.wav", fakeContext(jest.fn()), {
        attempts: 3,
        sleep,
      }),
    ).rejects.toThrow();

    expect(sleep).toHaveBeenNthCalledWith(1, 300);
    expect(sleep).toHaveBeenNthCalledWith(2, 600);
  });
});
