// The service worker's decisions, kept pure so vitest can check them without a browser.
// Loaded by sw.js as an ES module; no build step touches either file.
//
// The rule that matters: an offline read must never look like a fresh one. Every digest the
// worker stores is stamped with when it was fetched, and every answer it gives from storage
// carries that stamp to the page, which says so on screen.

export const CACHE = "pulse-v1";
export const SHELL = ["/", "/index.html", "/manifest.webmanifest", "/icons/icon-192.png"];
export const LATEST = "/api/digest/latest";

export const FETCHED_AT = "x-pulse-fetched-at";
export const OFFLINE_FETCHED_AT = "x-pulse-offline-fetched-at";

/** Which strategy a request gets. Anything not listed goes straight to the network. */
export function routeFor(url, method, mode) {
  if (method !== "GET") return "network";
  const path = url.pathname;
  if (path.startsWith("/api/digest/")) return "digest";
  if (path.startsWith("/api/")) return "network";
  if (mode === "navigate") return "shell";
  if (path.startsWith("/assets/") || path.startsWith("/icons/") || path === "/manifest.webmanifest") {
    return "static";
  }
  return "network";
}

/** The cache key for a request: path only, so a `?token=` never ends up in storage. */
export function cacheKey(url) {
  return `${url.origin}${url.pathname}`;
}

export function cacheable(response) {
  return response.status === 200;
}

/** A 502 from `tailscale serve` means the server is down, just as a network error does. */
export function serverDown(response) {
  return response.status >= 500;
}

async function copyWith(response, name, value) {
  const headers = new Headers(response.headers);
  headers.set(name, value);
  const body = await response.clone().arrayBuffer();
  return new Response(body, { status: response.status, statusText: response.statusText, headers });
}

export function stamp(response, now) {
  return copyWith(response, FETCHED_AT, now.toISOString());
}

export function offlineCopy(cached) {
  return copyWith(cached, OFFLINE_FETCHED_AT, cached.headers.get(FETCHED_AT) ?? "");
}

/** Network first; on failure, the stored copy — marked as such — or the failure itself. */
export async function digestFirstFromNetwork(url, { fetchFn, cache, now }) {
  const key = cacheKey(url);
  let response;
  try {
    response = await fetchFn();
  } catch (error) {
    const cached = await cache.match(key);
    if (cached) return offlineCopy(cached);
    throw error;
  }
  if (serverDown(response)) {
    const cached = await cache.match(key);
    return cached ? offlineCopy(cached) : response;
  }
  if (cacheable(response)) await cache.put(key, await stamp(response, now()));
  return response;
}

/** The hashed bundle files index.html refers to, so install can store them up front. */
export function assetsIn(html) {
  const found = new Set();
  for (const match of html.matchAll(/(?:src|href)="\.?\/?(assets\/[^"]+)"/g)) {
    found.add(`/${match[1]}`);
  }
  return [...found];
}
