/**
 * The API's public base URL, read on the server at request time.
 * `API_URL` is runtime configuration (one container image serves any
 * environment); `NEXT_PUBLIC_API_URL` is inlined at build time and stays as
 * the development fallback.
 */
export function getApiBaseUrl(): string {
  return process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}
