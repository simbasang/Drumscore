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

describe("loadAudioBuffer", () => {
  it("should fetch and decode audio data from the given URL", async () => {
    const arrayBuffer = new ArrayBuffer(8);
    const decodedBuffer = { duration: 12.5 };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      arrayBuffer: () => Promise.resolve(arrayBuffer),
    } as unknown as Response);
    const decodeAudioData = jest.fn().mockResolvedValue(decodedBuffer);
    const context = fakeContext(decodeAudioData);

    const result = await loadAudioBuffer("http://localhost:8000/audio.wav", context);

    expect(global.fetch).toHaveBeenCalledWith("http://localhost:8000/audio.wav");
    expect(decodeAudioData).toHaveBeenCalledWith(arrayBuffer);
    expect(result).toBe(decodedBuffer);
  });

  it("should throw when the fetch response is not ok", async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false } as Response);
    const decodeAudioData = jest.fn();
    const context = fakeContext(decodeAudioData);

    await expect(loadAudioBuffer("http://localhost:8000/audio.wav", context)).rejects.toThrow(
      "Failed to load audio",
    );
    expect(decodeAudioData).not.toHaveBeenCalled();
  });
});
