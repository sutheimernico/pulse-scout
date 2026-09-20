# pulse-scout — Project (Source of Truth)

A daily digest of the AI and tech world, read on a phone in five minutes. Its job is not to
show everything that happened — it is to throw away 99% of it and present the rest so that
Nico gets better at his work. Everything runs locally on his laptop and costs nothing.

---

# Part I — Specification

Full design: `docs/superpowers/specs/2026-08-07-pulse-scout-design.md`. This section is the
short form; when the two disagree, the spec wins until this file is updated.

## 1 · Vision & non-negotiables

Five minutes a day, on the phone, first thing in the morning. Two tiers: a short **Pflicht**
section with real substance and an explicit "why this concerns you", and a **Kür** section of
one-liners that exists only so a name has been read once.

Non-negotiables:

- **No running costs, ever.** No paid APIs, no paid cloud, no subscriptions.
- **The digest is written by a local model** (Ollama, CPU only — no GPU is available in WSL).
- **Third-party feed text is never committed.** It is someone else's copyrighted work.
- **Five minutes means five minutes.** Any feature that lengthens the daily read needs a
  deliberate decision.

## 2 · Architecture

A funnel where the language model comes last, because throughput on the target hardware is the
binding constraint (measured: 18,1 tokens/s intake, 4,5 tokens/s generation):

1. **Fetch** — RSS/Atom and open JSON APIs, ~400 items, no model.
2. **Dedupe and rank** — collapse the same story across sources (itself the strongest
   importance signal), weight by engagement numbers and a keyword profile. ~40 remain. No model.
3. **Score** — the small model rates those 40 for job relevance, one short prompt each.
4. **Write** — the 7B model sees only the top 12 and produces ~700 tokens: five judgements
   plus the connecting thread. The Kür lines need no model at all.

Threads across days are found by **embeddings**, not by the language model — that is precisely
the local model's weakest area, and cosine similarity answers "same topic?" deterministically.

## 3 · Scope

The topic list is derived from what Nico's repositories actually contain, read on 2026-08-07
rather than assumed. He is a fullstack developer with a backend emphasis, currently working on
architecture questions — not a data engineer, which was the initial wrong premise.

**Tier 1 — his job.** Backend (Python 3.12, FastAPI, SQLModel, SQLAlchemy, Alembic,
PostgreSQL), frontend (React 19, TypeScript, Vite, Tailwind 4, React Aria, Recharts),
architecture (both pattern writing and real case studies at scale), and his cloud stack
(Azure Container Apps/Functions/Key Vault, Pulumi, Azure DevOps, Sentry, OpenTelemetry).

**Tier 2 — AI models and releases.** A standing interest: what shipped and is it stronger.
HuggingFace's trending list answers that with numbers rather than announcements.

**Tier 3 — broad awareness.** Security, hardware, crypto/fintech, founders, aggregators.

**Out, deliberately:** dbt and the data-tooling ecosystem (a different team's concern);
Terraform (they use Pulumi); Kubernetes and CNCF (they use Container Apps, no AKS); SQL Server
(they use PostgreSQL and Snowflake); Product Management, Design and Marketing (verified to be
monthly opinion blogs with no daily volume).

The five Pflicht slots are filled by score, capped at three per tier — otherwise a busy AI
news day would push his own job out of his own digest.

## 4 · Data model

- `.cache/raw/` — raw feed responses. Gitignored, regenerable, third-party copyright.
- SQLite — items, sources, scores, threads, finished digests.
- `data/sources.toml` — the verified source list, hand-maintained.
- `data/` otherwise — derived artefacts only, safe to commit.

## 5 · Tech stack

Python 3.11+ (uv, ruff, pytest) for the pipeline and API; FastAPI serving a React/Vite PWA as
static files; SQLite; Ollama for scoring, writing and embeddings. Same shape as equity-scout,
which already runs this pattern on the same machine. Every network and model call sits behind
a seam and is faked in tests.

## 6 · Acceptance criteria

**Stage 1** is done when Nico reads a real digest on his phone on five consecutive days
without opening a laptop.

**Stage 2** is done when a thread correctly links one story across at least three
non-consecutive days.

---

# Part II — Plan & working method

## Status

**2026-09-20 — phases 1 and 2 built.** Implementation plan written
(`docs/superpowers/plans/2026-09-20-pulse-scout-v1.md`, 25 tasks) and tasks T1–T17 delivered.
The pipeline runs end to end. Phase 3 (API and PWA) and phase 4 (timer) are next.

Three things the live source list forced, each verified by fetching the URL rather than by
reasoning about it:

- The Hacker News entry returned the twenty *newest* submissions, which have one or two points
  each, so the "points + comments" signal it declared was empty. Corrected.
- All three Nitter mirrors are dead (connection refused). Retired. Anthropic — which publishes
  no RSS at all — is now covered only by GitHub release atoms and the aggregators.
- Most feeds are archives, not news streams: one call to ThoughtWorks Insights returns 2.722
  entries going back to 2008. Items are cut to a 72-hour publication window, and a persistent
  seen-set stops the funnel re-processing the same snapshots every morning.

Open for Nico: read the spec through; decide on a git remote; test Reddit and the CISA
advisory feeds from home; re-run the throughput benchmark on an idle machine (ADR 0001).

## Roadmap

- **Phase 0** — scaffold, spec, verified source list. Done 2026-08-07.
- **Phase 1** — fetch and dedupe, no model involved. Done 2026-09-20, live-verified.
- **Phase 2** — scoring and writing; the first real digest on disk. Done 2026-09-20 (T13–T17).
- **Phase 3** — API and PWA; the first digest on the phone. ← current
- **Phase 4** — timer, catch-up for missed runs, five days of daily use.
- **Phase 5** — stage 2: embeddings, threads, day counters, Sunday arc.

## Working method

Interactive sessions with Nico, plus an autonomous loop for well-specified backlog items. The
loop rules are global (`~/private/AUTOPILOT.md`); this project adds no exceptions to them.

Gate: `uv run pytest -q` green **and** `uv run ruff check .` clean. Never commit a red gate.

**Session-start reminder.** `scripts/session_start_status.sh` runs at the start of every
session under `~/private` (registered in `~/private/.claude/settings.local.json`) and prints
the current phase plus the single next step. It derives that state from the repository — open
checkboxes in `PLAN.md`, whether a plan document exists, how many source modules are present —
rather than from a hand-maintained status line, because a status line nobody updates is worse
than none. Update the script if the phase logic stops matching reality.

## §Decisions (closed, dated)

| # | Date | Decision |
|---|---|---|
| D1 | 2026-08-07 | Two tiers: Pflicht with substance, Kür as one-liners |
| D2 | 2026-08-07 | The digest is written locally, not by the Claude API. Claude argued against this twice with measurements; Nico decided, and the decision stands |
| D3 | 2026-08-07 | Threading by embeddings, not by the language model |
| D4 | 2026-08-07 | PWA in the equity-scout pattern, not a native app |
| D5 | 2026-08-07 | Topics narrowed: Product/Design/Marketing and dbt dropped |
| D6 | 2026-08-07 | Stage 1 first, stage 2 on top of it |
| D7 | 2026-08-07 | Tier 1 is fullstack and architecture, derived from the actual employer stack rather than assumed. Also removed Terraform, Kubernetes and SQL Server — none of which they use |
| D8 | 2026-08-07 | At most three of the five Pflicht slots may come from one tier |
| D9 | 2026-09-20 | Items are cut to a 72-hour publication window and a persistent seen-set keyed by canonical URL. The configured feeds are archives, not streams — without this the funnel re-processes ~570 items every morning |
| D10 | 2026-09-20 | The Kür is capped at 15 lines (5 + 15 = the 12–20 items D1 budgets). The spec said "one line per item" without a limit, which would have been 35 lines |
| D11 | 2026-09-20 | Pflicht is *up to* five. Below the model's threshold a slot stays empty and the digest says so, rather than being filled to reach a round number |
| D12 | 2026-09-20 | The writer's output is validated mechanically: every judgement must name a fetched item, and every number in the prose must appear in that item's own text. A failure fails the run |
| D13 | 2026-09-20 | Phases 1–2 add no runtime dependencies. urllib, ElementTree, json, sqlite3, tomllib. FastAPI and uvicorn enter with phase 3 |

## §Open inputs (Needs Nico)

- **Git remote and visibility** — nothing is pushed anywhere until Nico decides. The repo
  contains no personal data, so public would be possible.
- **Reddit and CISA from home** — both fail here with what looks like an IP block. Reddit
  would restore a relevance signal; CISA would strengthen the security category. Neither is
  load-bearing.
- **Five-day verdict after stage 1** — does the digest actually get read, or does it become
  the sixteenth unopened source?
