import type { Digest } from "./types";

export type LoadResult =
  | { kind: "ok"; digest: Digest; offlineSince: string | null }
  | { kind: "unauthorized" }
  | { kind: "none" }
  | { kind: "unreachable" };

/**
 * The token arrives once in the URL (`?token=…`). The first API call carries it, the server
 * answers with an httpOnly cookie, and the URL is cleaned so the token does not stay in the
 * address bar, the history or a home-screen shortcut.
 */
export function takeTokenFromUrl(location: Location, history: History): string | null {
  const params = new URLSearchParams(location.search);
  const token = params.get("token");
  if (!token) return null;
  params.delete("token");
  const rest = params.toString();
  history.replaceState(null, "", `${location.pathname}${rest ? `?${rest}` : ""}${location.hash}`);
  return token;
}

export async function loadLatest(token: string | null): Promise<LoadResult> {
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  let response: Response;
  try {
    response = await fetch(`/api/digest/latest${query}`, { credentials: "same-origin" });
  } catch {
    return { kind: "unreachable" };
  }
  if (response.status === 401) return { kind: "unauthorized" };
  if (response.status === 404) return { kind: "none" };
  if (!response.ok) return { kind: "unreachable" };
  const digest = (await response.json()) as Digest;
  // Set by the service worker when it answered from its cache instead of the network.
  const offlineSince = response.headers.get("x-pulse-offline-fetched-at");
  return { kind: "ok", digest, offlineSince };
}
