// The stored digest record, exactly as `core/digest.py` serialises it. The API passes it
// through untouched, so these fields are the Python dataclasses' fields.

export interface Card {
  headline: string;
  body: string;
  why_you: string;
  url: string | null;
  source_name: string;
  tier: number;
  item_key: string;
  // Absent on digests built before the faithfulness guard existed.
  quoted?: boolean;
}

export interface KuerLine {
  title: string;
  url: string | null;
  source_name: string;
  tier: number;
}

export interface Guard {
  model: string;
  checked: number;
  rejected: number;
  unreadable: number;
  seconds: number;
  quoted_cards: number;
}

export interface Digest {
  digest_date: string;
  generated_at: string;
  cards: Card[];
  thread: string;
  kuer: KuerLine[];
  counters: Record<string, number>;
  read_seconds: number;
  notes: string[];
  guard?: Guard | Record<string, never>;
}
