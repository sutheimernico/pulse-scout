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

**Intentionally empty.** The design is approved, but the implementation plan is not written
yet — that is the next step (`writing-plans`). The loop must NOT invent tasks here; on an
empty backlog it exits.

## Needs Nico (loop cannot do these itself)

- Git remote and public-visibility decision before any first push.
- Test Reddit and the CISA advisory feeds from the home network — both fail from the build
  environment with what looks like an IP block rather than a missing key.
- The five-day verdict after stage 1: does the digest actually get read?
