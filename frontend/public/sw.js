// pulse-scout service worker. Registered as a module, from main.tsx, in production builds only.
// Shell and bundle: cache first. The digest: network first, stored copy when offline — and the
// stored copy is always labelled with when it was fetched (see sw-strategy.js).

import {
  CACHE,
  LATEST,
  SHELL,
  assetsIn,
  cacheKey,
  cacheable,
  digestFirstFromNetwork,
  routeFor,
  stamp,
} from "./sw-strategy.js";

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE);
      await cache.addAll(SHELL);
      const index = await (await fetch("/index.html")).text();
      await cache.addAll(assetsIn(index));
      // Best effort: with the token cookie already set, today's digest is readable offline
      // from the very first visit. Without it (401) nothing is stored.
      try {
        const response = await fetch(LATEST, { credentials: "same-origin" });
        if (cacheable(response)) {
          await cache.put(cacheKey(new URL(LATEST, self.location.origin)), await stamp(response, new Date()));
        }
      } catch {
        // Offline during install: the first online read fills the cache instead.
      }
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      for (const name of await caches.keys()) {
        if (name !== CACHE) await caches.delete(name);
      }
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  const route = routeFor(url, event.request.method, event.request.mode);

  if (route === "digest") {
    event.respondWith(
      caches.open(CACHE).then((cache) =>
        digestFirstFromNetwork(url, {
          fetchFn: () => fetch(event.request),
          cache,
          now: () => new Date(),
        }),
      ),
    );
  } else if (route === "shell") {
    event.respondWith(
      fetch(event.request).catch(async () => {
        const cache = await caches.open(CACHE);
        return (await cache.match("/index.html")) ?? (await cache.match("/")) ?? Response.error();
      }),
    );
  } else if (route === "static") {
    event.respondWith(
      caches.open(CACHE).then(async (cache) => {
        const hit = await cache.match(url.pathname);
        if (hit) return hit;
        const response = await fetch(event.request);
        if (cacheable(response)) await cache.put(url.pathname, response.clone());
        return response;
      }),
    );
  }
});
