import type { AudioBufferLike, AudioContextLike } from "./SyncedPlayer";

export interface DecodableAudioContext extends AudioContextLike {
  decodeAudioData(data: ArrayBuffer): Promise<AudioBufferLike>;
}

export async function loadAudioBuffer(
  url: string,
  context: DecodableAudioContext,
): Promise<AudioBufferLike> {
  const response = await fetch(url);

  if (!response.ok) {
    throw new Error(`Failed to load audio: ${url}`);
  }

  const arrayBuffer = await response.arrayBuffer();
  return context.decodeAudioData(arrayBuffer);
}
