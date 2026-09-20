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

### Phase 1 — the deterministic funnel (no model)

- [ ] **T1** Measure the model first: `scripts/bench_ollama.py`, both models, prefix-cache check,
      result to `data/benchmarks/` + `docs/adr/0001-throughput-budget.md`
- [ ] **T2** `models.py` + `core/canonical.py` — Item/Cluster dataclasses, URL canonicalisation, `item_key`
- [ ] **T3** `sources/http.py` — the network seam (Fetcher protocol, UrllibFetcher, conditional GET)
- [ ] **T4** `sources/cache.py` — raw bodies into `.cache/raw/<date>/`, 14-day prune, path guard
- [ ] **T5** `sources/feeds.py` — RSS + Atom via ElementTree, body sniffing, BOM tolerance
- [ ] **T6** `sources/json_api.py` — HuggingFace / HN / Lobsters / CISA adapters
- [ ] **T7** `sources/collect.py` — drive all sources, fragile handling, 30 % failure abort, FetchReport
- [ ] **T8** `scripts/fetch_once.py` + live source reality check → `data/source_health.json`,
      fix the HN query and retire the three dead nitter entries
- [ ] **T9** `core/dedupe.py` — canonical-URL identity, then title Jaccard ≥ 0,60 in a 48 h window
- [ ] **T10** `data/profile.toml` + `core/ranking.py` — keyword profile from D7, the explicit score formula
- [ ] **T11** `store/db.py` + `store/repo.py` — SQLite schema v1, seen-set keyed by `item_key`
- [ ] **T12** `pipeline.py` + `scripts/run_funnel.py` — phase-1 wiring with real funnel counters

### Phase 2 — the model and the digest

- [ ] **T13** `llm/ollama.py` — the model seam (generate + embed, timings, fake in tests)
- [ ] **T14** `llm/scorer.py` + `llm/prompts.py` — 1.5b pass, strict parsing, both ranks persisted
- [ ] **T15** `core/selection.py` — 12 finalists, ≤ 5 Pflicht with the 3-per-tier cap, ≤ 15 Kür
- [ ] **T16** `llm/writer.py` + `core/validate.py` — 7b pass and the honesty validator (run fails on invention)
- [ ] **T17** `core/digest.py` + `scripts/build_digest.py` — assembly, persistence, Markdown, read-time
- [ ] **T18** First real end-to-end run, measured, recorded in `data/benchmarks/`

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

- Git remote and public-visibility decision before any first push.
- Test Reddit and the CISA advisory feeds from the home network — both fail from the build
  environment with what looks like an IP block rather than a missing key.
- The five-day verdict after stage 1: does the digest actually get read?
- `ollama pull nomic-embed-text` before phase 5 — free, ~270 MB, but a local download.
