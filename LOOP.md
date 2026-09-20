# pulse-scout — LOOP (per-iteration prompt for the autonomous build agent)

You are a fresh headless agent. You do ONE high-value thing, verify it, commit it, and exit.
Progress lives on disk (this file, `PROJECT.md`/`PLAN.md`, git history, `AUTOPILOT_LOG.md`) —
never in context.

## Per-iteration protocol

1. Read `~/private/AUTOPILOT.md` (global rules), then this `LOOP.md`, then `PLAN.md` + `PROJECT.md`.
2. Confirm you are on branch `autopilot/work` (the runner guarantees this; if not, stop).
3. Pick the SINGLE highest-value open `- [ ]` task (top-to-bottom, earlier phases first). If a
   phase boundary is reached, run the once-per-phase self-challenge/SOTA step first (write an
   ADR under `docs/adr/` if it changes the plan).
   **If the backlog is empty, exit immediately — do not invent tasks.**
4. Do that one task. Small, reviewable diff. Read existing code before writing; match conventions.
   New logic ships with a test. Network and Ollama access stay behind the seams and are faked.
5. Run the gate: `uv run pytest -q` (green) AND `uv run ruff check .` (clean). If red, fix or revert.
6. On green: commit (Conventional Commits, English, imperative), check off the task in `PLAN.md`,
   append a one-line note to `AUTOPILOT_LOG.md`. Then exit.
7. If a task needs a paid resource or a Nico-only input: move it to "Needs Nico", pick another,
   or exit. Never sign up for anything paid. Never fake data or metrics.

## Project-specific hard constraints (never override)

- **Local & free.** Free feeds and key-less APIs only; Ollama locally. No paid API — not even
  "just to compare". Nico decided on the local model with the trade-off on the table.
- **Throughput is the binding constraint.** Measured on this machine: 18,1 tokens/s intake,
  4,5 tokens/s generation, CPU only. Any change that enlarges the model's context or output
  costs real minutes per day. Prefer moving work into deterministic code over enlarging a prompt.
- **Raw feed text never gets committed.** `.cache/` is gitignored for a reason.
- **Never fabricate a digest item.** No invented headlines, no invented sources, no invented
  numbers. A failed run must fail visibly.
- **Content type is not trustworthy.** Several verified feeds report `text/html` and return
  valid XML. Sniff the body, not the header.
- **Fragile sources must not break the run.** A source marked `fragile = true` in
  `data/sources.toml` is skipped with a warning, never a failed run. (The three Nitter mirrors
  that carried this flag were retired on 2026-09-20 — all dead. Nothing is marked fragile right
  now, and the mechanism stays because the next bonus source will need it.) A *non-fragile*
  source failing is recorded loudly, and above 30 % of them the whole run aborts.
- **Pin new deps** with a one-line justification; simplest solution that meets the task (YAGNI).
  The config is TOML precisely so that reading it needs no dependency at all.

## Gate (objective done-check)

`uv run pytest -q` green + `uv run ruff check .` clean. Commit only a green gate.

## Where things are

- Spec: `docs/superpowers/specs/2026-08-07-pulse-scout-design.md` — **read §3/D7 for the
  topic set, not §1 or §4**, which still describe a premise D7 revoked.
- Plan: `docs/superpowers/plans/2026-09-20-pulse-scout-v1.md` · ADRs: `docs/adr/`
- Sources: `data/sources.toml` (verified; the bottom section lists what is broken — don't re-add)
- Code: `src/pulse_scout/` (one responsibility per file) · Tests: `tests/` · CLIs: `scripts/`
- Raw cache: `.cache/` (gitignored) · Derived artifacts: `data/`
- Run locally: `uv run python scripts/<name>.py`
