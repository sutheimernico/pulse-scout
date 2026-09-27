// Pure presentation helpers. Nothing here derives a number the digest does not already hold:
// the API computes nothing, and neither does the screen (AGENTS.md).

import type { KuerLine } from "./types";

// Mirrors TIER_LABELS in src/pulse_scout/core/selection.py — the Markdown digest uses those.
export const TIER_LABELS: Record<number, string> = {
  1: "Dein Stack",
  2: "KI-Modelle",
  3: "Drumherum",
};

const DAY_MS = 24 * 60 * 60 * 1000;

function utcDate(isoDay: string): Date {
  const [year, month, day] = isoDay.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

/** "2026-09-27" → "Sonntag, 27. September". The digest's own date, never today's. */
export function formatDigestDate(isoDay: string): string {
  return new Intl.DateTimeFormat("de-DE", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  }).format(utcDate(isoDay));
}

/** "2026-09-27T21:30:00+02:00" → "21:30" — the local wall-clock time the run finished. */
export function formatStand(generatedAt: string): string {
  return generatedAt.slice(11, 16);
}

export function readTimeLabel(seconds: number): string {
  if (seconds < 60) return "< 1 min";
  return `≈ ${Math.round(seconds / 60)} min`;
}

/** Width of the funnel bar in percent. Visible when anything got through, empty when not. */
export function funnelShare(seen: number, kept: number): number {
  if (seen <= 0 || kept <= 0) return 0;
  return Math.max(1, Math.min(100, (kept / seen) * 100));
}

export interface KuerGroup {
  tier: number;
  label: string;
  lines: KuerLine[];
}

export function groupKuer(lines: KuerLine[]): KuerGroup[] {
  const tiers = [...new Set(lines.map((line) => line.tier))].sort((a, b) => a - b);
  return tiers.map((tier) => ({
    tier,
    label: TIER_LABELS[tier] ?? `Stufe ${tier}`,
    lines: lines.filter((line) => line.tier === tier),
  }));
}

/** Today's date in Berlin as "YYYY-MM-DD" — the zone the digest is dated in (D-P11). */
export function berlinToday(now: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Berlin",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

/**
 * Whole days between the digest's date and today. The run is in the evening, so yesterday's
 * digest is the current one every morning; from two days on, a run was missed.
 */
export function digestAgeDays(digestDate: string, today: string): number {
  return Math.round((utcDate(today).getTime() - utcDate(digestDate).getTime()) / DAY_MS);
}

export function staleNotice(digestDate: string, today: string): string | null {
  const age = digestAgeDays(digestDate, today);
  if (age < 2) return null;
  return `Seit ${age} Tagen kein neuer Digest — der abendliche Lauf ist vermutlich ausgefallen.`;
}

/** "2026-09-27T05:12:00.000Z" → "27.09., 07:12" in Berlin time. */
export function formatFetchedAt(iso: string): string {
  return new Intl.DateTimeFormat("de-DE", {
    timeZone: "Europe/Berlin",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}

export function rank(index: number): string {
  return String(index + 1).padStart(2, "0");
}
