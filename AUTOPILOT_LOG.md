# pulse-scout — autopilot log

One line per iteration. Newest last.

- 2026-08-07 — Phase 0: scaffold created (interactive session, not loop). Spec written and
  approved-pending. Source list verified by live fetch (~90 feeds). Ollama throughput measured
  on target hardware: 18.1 tok/s prompt, 4.5 tok/s generation, CPU only.
- 2026-09-20 — Plan written (`docs/superpowers/plans/2026-09-20-pulse-scout-v1.md`, 25 tasks,
  9 findings against the spec) and `PLAN.md` backlog filled. Then phases 1 and 2 built:
  T1–T17 in 15 atomic commits on `autopilot/work`. Gate at the end: 231 tests green, ruff clean.
  Live-verified: the funnel runs against all 60 real sources (570 items seen → 40 candidates).
  Corrections the live run forced: the Hacker News URL returned the 20 newest submissions
  (~1 point each), so the configured "points + comments" signal was empty; all three Nitter
  mirrors are dead (connection refused), so Anthropic coverage now rests on GitHub atoms and
  the aggregators; the feed corpus is archives, not streams (ThoughtWorks alone returns 2.722
  entries back to 2008), so items are cut to a 72-hour publication window. Throughput measured
  but contaminated by concurrent sessions (load 38–57 on 16 threads) — ADR 0001 owes an idle
  re-measurement. Correction to our own instrument: `prompt_eval_count` reports the full prompt
  whether or not the prefix was cached, so the cache metric now measures time (8,43 s → 0,22 s
  on an identical prefix — the cache does work).
