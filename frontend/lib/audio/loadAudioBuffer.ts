import type { AudioBufferLike, AudioContextLike } from "./SyncedPlayer";

export interface DecodableAudioContext extends AudioContextLike {
  decodeAudioData(data: ArrayBuffer): Promise<AudioBufferLike>;
  close(): Promise<void>;
}

export interface RetryOptions {
  attempts?: number;
  delayMs?: (attempt: number) => number;
  sleep?: (ms: number) => Promise<void>;
}

function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function fetchAndDecode(
  url: string,
  context: DecodableAudioContext,
): Promise<AudioBufferLike> {
  const response = await fetch(url);

  if (!response.ok) {
    throw new Error(`Failed to load audio: ${url} (status ${response.status})`);
  }

  const arrayBuffer = await response.arrayBuffer();
  return context.decodeAudioData(arrayBuffer);
}

export async function loadAudioBuffer(
  url: string,
  context: DecodableAudioContext,
  retryOptions: RetryOptions = {},
): Promise<AudioBufferLike> {
  const attempts = retryOptions.attempts ?? 3;
  const delayMs = retryOptions.delayMs ?? ((attempt: number) => 300 * 2 ** (attempt - 1));
  const sleep = retryOptions.sleep ?? defaultSleep;

  let lastError: unknown;

  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fetchAndDecode(url, context);
    } catch (error) {
      lastError = error;
      console.error(`[loadAudioBuffer] attempt ${attempt}/${attempts} failed for ${url}:`, error);
      if (attempt < attempts) {
        await sleep(delayMs(attempt));
      }
    }
  }

  throw lastError instanceof Error ? lastError : new Error(`Failed to load audio: ${url}`);
}
