# pulse-scout — Plan (AUTOPILOT-driven build backlog)

**Source of truth for design:** `docs/superpowers/specs/2026-08-07-pulse-scout-design.md`
Personal rules (`~/.claude/CLAUDE.md`) + global loop rules (`~/private/AUTOPILOT.md`) apply.

This file is the binding backlog for the autonomous loop. Each iteration picks the SINGLE
highest-value open `- [ ]` task, does it on `autopilot/work`, runs the gate, commits only if
green, checks the box, and appends one line to `AUTOPILOT_LOG.md`.

## Iron principles (never overridden)

- **Local & free only.** Free RSS/Atom feeds and key-less JSON APIs; Ollama on the local
  machine. No paid API, no paid cloud, no signup. A task needing a paid resource or a
  Nico-only input goes to "Needs Nico", never faked.
- **Gate is objective:** `uv run pytest -q` green AND `uv run ruff check .` clean. Never commit red.
- **One change per iteration.** No bundling. No speculative abstractions (YAGNI).
- **New logic ships with a test.** No live network in tests — fetching and Ollama both sit
  behind a seam and are faked.
- **Raw feed text is never committed.** It is third-party copyrighted material and lives in
  `.cache/raw/` (gitignored). Only derived data goes into `data/`.
- **No fabricated digests.** If the model produces nothing usable, the run fails loudly. A
  digest with invented items is worse than no digest — the whole product is a trust claim.
- **Respect the sources.** Identify with the configured user agent, poll at most hourly, and
  honour the documented limits (Hacker News 10k/h, arXiv-style etiquette elsewhere).

## Status

- [x] **Phase 0 — Scaffold** (2026-08-07: structure, spec, verified source list, throughput
      measured, gate green on the empty skeleton)

## Backlog

Derived from `docs/superpowers/plans/2026-09-20-pulse-scout-v1.md` (2026-09-20). That document
holds the file paths, acceptance criteria and the decisions behind each task — this list is the
loop's index into it. Work top to bottom.

### Phase 1 — the deterministic funnel (no model) — **complete 2026-09-20**

- [x] **T1** Measure the model first: `scripts/bench_ollama.py`, both models, prefix-cache check,
      result to `data/benchmarks/` + `docs/adr/0001-throughput-budget.md`
      — done, but the run was contaminated by other sessions on the machine (load 38–57 on
      16 threads). ADR 0001 item 2: **re-measure on an idle machine** before tuning anything.
- [x] **T2** `models.py` + `core/canonical.py` — Item/Cluster dataclasses, URL canonicalisation, `item_key`
- [x] **T3** `sources/http.py` — the network seam (Fetcher protocol, UrllibFetcher, conditional GET)
- [x] **T4** `sources/cache.py` — raw bodies into `.cache/raw/<date>/`, 14-day prune, path guard
- [x] **T5** `sources/feeds.py` — RSS + Atom via ElementTree, body sniffing, BOM tolerance
- [x] **T6** `sources/json_api.py` — HuggingFace / HN / Lobsters / CISA adapters
- [x] **T7** `sources/collect.py` — drive all sources, fragile handling, 30 % failure abort, FetchReport
- [x] **T8** `scripts/fetch_once.py` + live source reality check → `data/source_health.json`,
      fix the HN query and retire the three dead nitter entries
- [x] **T9** `core/dedupe.py` — canonical-URL identity, then title Jaccard ≥ 0,60 in a 48 h window
- [x] **T10** `data/profile.toml` + `core/ranking.py` — keyword profile from D7, the explicit score formula
- [x] **T11** `store/db.py` + `store/repo.py` — SQLite schema v1, seen-set keyed by `item_key`
- [x] **T12** `pipeline.py` + `scripts/run_funnel.py` — phase-1 wiring with real funnel counters

### Phase 2 — the model and the digest — **T13–T17 complete 2026-09-20**

- [x] **T13** `llm/ollama.py` — the model seam (generate + embed, timings, fake in tests)
      — built first, before T1, so the benchmark did not need a throwaway HTTP client.
- [x] **T14** `llm/scorer.py` + `llm/prompts.py` — 1.5b pass, strict parsing, both ranks persisted
- [x] **T15** `core/selection.py` — 12 finalists, ≤ 5 Pflicht with the 3-per-tier cap, ≤ 15 Kür
- [x] **T16** `llm/writer.py` + `core/validate.py` — 7b pass and the honesty validator (run fails on invention)
- [x] **T17** `core/digest.py` + `scripts/build_digest.py` — assembly, persistence, Markdown, read-time
- [x] **T18** First real end-to-end run, measured, recorded in `data/benchmarks/`
      — worked end to end in 260 s. Content quality is finding F9 in the flesh: the model
      turned "agreeing to slow AI development" into "agreed to stop it" and wrote a
      content-free relevance line. The validator passed it, correctly — nothing checkable
      was invented. See the plan's outcome section.

### Phase 3 — API and PWA

- [ ] **T19** `api.py` + `scripts/serve.py` — read-only endpoints, fail-closed token gate (first new deps)
- [ ] **T20** `frontend/` — React 19 + Vite PWA built from the approved mockup
- [ ] **T21** Manifest, service worker, offline read of the last digest with a visible timestamp

### Phase 4 — operation

- [ ] **T22** systemd user timer + idempotent `scripts/daily.sh` + `docs/ops.md`
- [ ] **T23** Five-day observation log (`docs/observations/`) — **needs Nico's verdict column**

### Phase 5 — stage 2 (threads), only after stage 1 runs daily

- [ ] **T24** `llm/embedder.py` + `core/threads.py` — embeddings, cosine threading, day counters
- [ ] **T25** "Läuft weiter" section and the Sunday arc

## Needs Nico (loop cannot do these itself)

- **Re-run `uv run python scripts/bench_ollama.py` on an idle machine.** ADR 0001 —
  every funnel-sizing decision waits on a measurement that is not drowned in contention.

- Git remote and public-visibility decision before any first push.
- Test Reddit and the CISA advisory feeds from the home network — both fail from the build
  environment with what looks like an IP block rather than a missing key.
- The five-day verdict after stage 1: does the digest actually get read?
- **Read one real digest before the five days start** (`data/digests/2026-09-20.md`).
  The machinery is honest; the prose from the 7B model on a quiet day is thin and, in the
  first run, subtly wrong in a way no validator can catch.
- `ollama pull nomic-embed-text` before phase 5 — free, ~270 MB, but a local download.
