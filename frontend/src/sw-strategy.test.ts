import { describe, expect, it } from "vitest";

import {
  FETCHED_AT,
  OFFLINE_FETCHED_AT,
  assetsIn,
  cacheKey,
  digestFirstFromNetwork,
  routeFor,
} from "../public/sw-strategy.js";

const ORIGIN = "https://wsl-claude.example.ts.net:8443";
const url = (path: string) => new URL(path, ORIGIN);

class FakeCache {
  store = new Map<string, Response>();
  async match(key: string) {
    return this.store.get(key)?.clone();
  }
  async put(key: string, response: Response) {
    this.store.set(key, response);
  }
}

const NOW = new Date("2026-09-27T19:40:00.000Z");
const digest = () =>
  new Response(JSON.stringify({ digest_date: "2026-09-27" }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

describe("routing", () => {
  it("sends each kind of request to its strategy", () => {
    expect(routeFor(url("/api/digest/latest"), "GET", "cors")).toBe("digest");
    expect(routeFor(url("/api/digest/2026-09-26"), "GET", "cors")).toBe("digest");
    expect(routeFor(url("/api/health"), "GET", "cors")).toBe("network");
    expect(routeFor(url("/"), "GET", "navigate")).toBe("shell");
    expect(routeFor(url("/assets/index-abc.js"), "GET", "no-cors")).toBe("static");
    expect(routeFor(url("/icons/icon-192.png"), "GET", "no-cors")).toBe("static");
    expect(routeFor(url("/api/digest/latest"), "POST", "cors")).toBe("network");
  });

  it("never keeps the token in a cache key", () => {
    expect(cacheKey(url("/api/digest/latest?token=secret"))).toBe(`${ORIGIN}/api/digest/latest`);
  });
});

describe("the digest when online", () => {
  it("returns the network answer and stores a stamped copy", async () => {
    const cache = new FakeCache();
    const response = await digestFirstFromNetwork(url("/api/digest/latest?token=t"), {
      fetchFn: async () => digest(),
      cache,
      now: () => NOW,
    });
    expect(response.headers.get(OFFLINE_FETCHED_AT)).toBeNull();
    const stored = await cache.match(`${ORIGIN}/api/digest/latest`);
    expect(stored?.headers.get(FETCHED_AT)).toBe(NOW.toISOString());
  });

  it("does not store a refusal", async () => {
    const cache = new FakeCache();
    const response = await digestFirstFromNetwork(url("/api/digest/latest"), {
      fetchFn: async () => new Response("{}", { status: 401 }),
      cache,
      now: () => NOW,
    });
    expect(response.status).toBe(401);
    expect(cache.store.size).toBe(0);
  });
});

describe("the digest when offline", () => {
  async function primed() {
    const cache = new FakeCache();
    await digestFirstFromNetwork(url("/api/digest/latest"), {
      fetchFn: async () => digest(),
      cache,
      now: () => NOW,
    });
    return cache;
  }

  it("falls back to the stored copy and says when it was fetched", async () => {
    const cache = await primed();
    const response = await digestFirstFromNetwork(url("/api/digest/latest"), {
      fetchFn: async () => {
        throw new TypeError("Failed to fetch");
      },
      cache,
      now: () => new Date(),
    });
    expect(response.headers.get(OFFLINE_FETCHED_AT)).toBe(NOW.toISOString());
    expect((await response.json()).digest_date).toBe("2026-09-27");
  });

  it("treats a gateway error from tailscale serve like a network error", async () => {
    const cache = await primed();
    const response = await digestFirstFromNetwork(url("/api/digest/latest"), {
      fetchFn: async () => new Response("bad gateway", { status: 502 }),
      cache,
      now: () => new Date(),
    });
    expect(response.status).toBe(200);
    expect(response.headers.get(OFFLINE_FETCHED_AT)).toBe(NOW.toISOString());
  });

  it("fails honestly when nothing was ever stored", async () => {
    const attempt = digestFirstFromNetwork(url("/api/digest/latest"), {
      fetchFn: async () => {
        throw new TypeError("Failed to fetch");
      },
      cache: new FakeCache(),
      now: () => NOW,
    });
    await expect(attempt).rejects.toThrow("Failed to fetch");
  });
});

describe("install", () => {
  it("finds the hashed bundle files in the built index.html", () => {
    const html =
      '<script type="module" crossorigin src="./assets/index-BBbD.js"></script>' +
      '<link rel="stylesheet" crossorigin href="./assets/index-BTah.css">' +
      '<link rel="manifest" href="/manifest.webmanifest">';
    expect(assetsIn(html)).toEqual(["/assets/index-BBbD.js", "/assets/index-BTah.css"]);
  });
});
