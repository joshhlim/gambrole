/**
 * Where the API lives. Defaults to the local dev server — but only outside a
 * production build: a deploy that forgot NEXT_PUBLIC_API_URL would otherwise
 * quietly point every phone at its own localhost and look merely "offline".
 * Null here makes every request fail with a message naming the missing
 * variable instead (see api.ts). Not a throw at module load: CI builds
 * without the variable, and prerendering must still succeed.
 */
export const API_URL: string | null =
  process.env.NEXT_PUBLIC_API_URL ??
  (process.env.NODE_ENV === "production" ? null : "http://localhost:8000");

export const API_URL_MISSING = "App misconfigured: NEXT_PUBLIC_API_URL is not set.";

if (API_URL === null && typeof window !== "undefined") {
  console.error(API_URL_MISSING);
}
