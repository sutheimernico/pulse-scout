# pulse-scout

A daily digest of the AI and tech world, read on a phone in five minutes. Runs entirely on a
local machine and costs nothing to operate.

## Status

**2026-08-07 — Phase 0 (scaffold).** Design approved, spec written, source list verified by
live fetch, local model throughput measured. No pipeline code yet.

## What makes it different from a news reader

The hard part is not collecting — it is discarding. Roughly 400 items come in per day and 5
go into the *Pflicht* section, each with an explicit line on why it concerns the reader's
actual job. The filter ratio is displayed at the top of the screen, because it is the product's
whole promise.

The second difference is memory. Stories are tracked across days by embedding similarity, so
the digest can say "day 23 of this thread, here is what changed" instead of presenting every
morning as if nothing happened before it.

## Honest harness (what makes the digest trustworthy)

- **Nothing is invented.** No fabricated headlines, sources or numbers. A run that produces
  nothing usable fails visibly rather than emitting something plausible.
- **Every source was verified by a live fetch**, not assumed. `data/sources.toml` lists what
  works and, at the bottom, what is verified broken — including several feed URLs that are
  widely cited but return HTML.
- **The funnel count on screen is real.** It reports the actual number of items seen and kept.
- **Sample data is always labelled as sample data**, in the interface and in any report.

## Scope

**In:** AI models and releases (the primary interest), Azure and cloud, then Development,
DevOps, Security, Hardware/IT, Crypto/Fintech, Founders.

**Out:** Product Management, Design and Marketing — verified to be low-frequency opinion blogs
without daily volume, so a daily digest would be empty most days.

## Quickstart (after `uv sync`)

```bash
# Prerequisites: Ollama running locally with the three models pulled
ollama pull qwen2.5:1.5b nomic-embed-text   # qwen2.5:7b is usually present already

cp .env.example .env        # then set PULSE_DASH_TOKEN to any long random string

uv run pytest -q            # gate part 1
uv run ruff check .         # gate part 2
```

Pipeline and web commands arrive with Phase 1–3; see `AGENTS.md` for the planned entry points.

## Stack

Python 3.11+ (uv, ruff, pytest) · FastAPI · SQLite · React + Vite as a PWA · Ollama for
scoring, writing and embeddings. No paid services, no cloud, no API keys.

Everything that touches the network or the model sits behind a seam and is faked in tests, so
the suite never needs connectivity.

## License

MIT — see `LICENSE`.
