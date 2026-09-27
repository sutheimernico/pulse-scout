import { describe, expect, it } from "vitest";

import {
  berlinToday,
  digestAgeDays,
  formatDigestDate,
  formatFetchedAt,
  formatStand,
  funnelShare,
  groupKuer,
  offlineNotice,
  rank,
  readTimeLabel,
  staleNotice,
} from "./format";

describe("dates", () => {
  it("names the digest's own day in German", () => {
    expect(formatDigestDate("2026-09-27")).toBe("Sonntag, 27. September");
    expect(formatDigestDate("2026-03-02")).toBe("Montag, 2. März");
  });

  it("shows the local time the run finished, as stored", () => {
    expect(formatStand("2026-09-27T21:30:00+02:00")).toBe("21:30");
  });

  it("knows Berlin's date even when UTC is still on the previous day", () => {
    expect(berlinToday(new Date("2026-09-27T22:30:00Z"))).toBe("2026-09-28");
    expect(berlinToday(new Date("2026-09-27T12:00:00Z"))).toBe("2026-09-27");
  });

  it("formats when an offline copy was fetched", () => {
    expect(formatFetchedAt("2026-09-27T05:12:00.000Z")).toBe("27.09., 07:12");
    expect(formatFetchedAt("")).toBeNull();
    expect(formatFetchedAt("gestern")).toBeNull();
  });

  it("labels an offline read even when the stamp is missing", () => {
    expect(offlineNotice("2026-09-27T05:12:00.000Z")).toContain("27.09., 07:12");
    expect(offlineNotice("")).toContain("Ladezeitpunkt unbekannt");
  });
});

describe("staleness", () => {
  it("counts whole days", () => {
    expect(digestAgeDays("2026-09-26", "2026-09-27")).toBe(1);
    expect(digestAgeDays("2026-03-28", "2026-03-30")).toBe(2); // across the DST switch
  });

  it("stays quiet about yesterday evening's digest in the morning", () => {
    expect(staleNotice("2026-09-27", "2026-09-27")).toBeNull();
    expect(staleNotice("2026-09-26", "2026-09-27")).toBeNull();
  });

  it("says so once a run was missed", () => {
    expect(staleNotice("2026-09-24", "2026-09-27")).toContain("Seit 3 Tagen");
  });
});

describe("header numbers", () => {
  it("labels the read time", () => {
    expect(readTimeLabel(16)).toBe("< 1 min");
    expect(readTimeLabel(250)).toBe("≈ 4 min");
  });

  it("sizes the funnel bar from the real counts and never invents a sliver", () => {
    expect(funnelShare(412, 5)).toBeCloseTo(1.21, 2);
    expect(funnelShare(10_000, 1)).toBe(1);
    expect(funnelShare(412, 0)).toBe(0);
    expect(funnelShare(0, 0)).toBe(0);
  });

  it("numbers the cards the way the mockup does", () => {
    expect(rank(0)).toBe("01");
    expect(rank(11)).toBe("12");
  });
});

describe("Kür", () => {
  it("groups by tier in tier order with the Python labels", () => {
    const groups = groupKuer([
      { title: "b", url: null, source_name: "x", tier: 3 },
      { title: "a", url: null, source_name: "x", tier: 1 },
      { title: "c", url: null, source_name: "x", tier: 3 },
    ]);
    expect(groups.map((g) => g.label)).toEqual(["Dein Stack", "Drumherum"]);
    expect(groups[1].lines.map((l) => l.title)).toEqual(["b", "c"]);
  });
});
