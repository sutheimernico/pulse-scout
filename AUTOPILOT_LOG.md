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
- 2026-09-20 — T18: first real end-to-end run against live sources with qwen2.5:7b, 260 s total
  (396 seen → 1 new, because the seen-set had already absorbed the day's items; writer 156
  tokens in 229 s; validator passed; digest written). Machinery honest — the digest itself says
  "Ruhiger Tag: nur 1 von 5 Plätzen" and that it was built without the model's scoring pass.
  Content is finding F9 in the flesh: the model turned "agreeing to slow AI development" into
  "agreed to stop it" and supplied a motive absent from the source, and the relevance line was
  content-free. No validator can catch that. **Needs Nico: read that digest before the
  five-day trial starts.** Stopped at the phase boundary — phases 1 and 2 complete and
  verified, phase 3 (API + PWA) untouched and open in PLAN.md.
