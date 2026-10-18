# pulse-scout

A daily digest of the AI and tech world, read on a phone in five minutes. Runs entirely on a
local machine and costs nothing to operate.

## Status

**2026-09-27 — stage 1 is built and running.** The pipeline fetches, dedupes, ranks, scores,
writes, fact-checks and stores a digest every evening at 20:30 (systemd user timer, catches up
missed days); a PWA serves it to the phone, offline too — verified in headless Chromium, not
yet on the real phone. What is left for stage 1 is that, and the five-day observation, which
only Nico can do (`docs/observations/2026-09-27-five-days.md`).

**2026-10-18 — reliability pass.** Between 09-28 and 10-15 the timer produced a digest on 17 of
18 days. From 10-16 on, none: another local project was holding the same Ollama, every model
call queued behind it, and one run hung for 40 hours before failing. A run now stops after a
two-hour wall-clock budget, and a run that writes no digest gives its fetched items back so the
retry still sees them. Details and what to do when a day is missing: `docs/ops.md`.

Plan and backlog: `docs/superpowers/plans/2026-09-20-pulse-scout-v1.md` and `PLAN.md`.
Operations — timer, server, phone access, logs, undo: `docs/ops.md`.

## On the phone

With Tailscale on, open once:

    https://<host>.<tailnet>.ts.net:8443/?token=<TOKEN>

`<TOKEN>` is `PULSE_DASH_TOKEN` from `.env` on the laptop (`grep PULSE_DASH_TOKEN .env`). The
server turns it into a cookie and the page removes it from the address bar. Then Chrome menu →
*App installieren*. The app shows the latest digest; without a connection, the last one it
loaded, marked "Offline — gespeicherte Fassung, zuletzt geladen am …".

`http://<tailscale-ip>:8430/?token=<TOKEN>` (the WSL node's Tailscale IP) works as an
online-only fallback: plain HTTP allows no service worker, so no offline copy and no install.

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
- **Every source was verified by a live fetch**, not assumed, and re-verified on 2026-09-20.
  `data/sources.toml` lists what works and, at the bottom, what is verified broken — including
  several widely cited feed URLs that return HTML, and the Nitter mirrors that died since.
  `data/source_health.json` holds the numbers from the last real run.
- **The model's output is checked mechanically before anyone sees it.** Every judgement must
  name an item that was actually fetched, and every number in the prose must occur in that
  item's own title or summary. A draft that fails either check fails the run.
- **Every factual sentence is checked against its source.** The first real digest passed all
  of the above and was still wrong ("agreed to slow" became "agreed to stop"). So each
  headline and body sentence goes back to the model as a yes/no question against the source
  text; what the source does not support is dropped, and a card with nothing left shows the
  source's own first sentence, marked "Originaltext der Quelle". On 119 hand-labelled
  sentences it caught 36 of 37 unfaithful ones and dropped 13 of 62 faithful ones
  (`data/benchmarks/2026-09-27-faithfulness-qwen2.5-7b-v2.json`). It does not check
  "Darum geht's dich an" or the Roter Faden — those are interpretation, not report.
- **The funnel count on screen is real.** It reports the actual number of items seen and kept.
- **Sample data is always labelled as sample data**, in the interface and in any report.

## Scope

Three tiers, derived from what the reader's repositories actually contain rather than from an
assumption about his job title:

**Tier 1 — his own work.** FastAPI, SQLModel, SQLAlchemy, Alembic, PostgreSQL; React 19,
TypeScript, Vite, Tailwind, React Aria; software architecture; Azure Container Apps, Pulumi,
Azure DevOps. **Tier 2 — AI models and releases.** **Tier 3 — broad awareness:** security,
hardware, crypto/fintech, founders, aggregators.

**Out:** dbt and the data-tooling ecosystem, Terraform, Kubernetes, SQL Server — none of which
he uses — plus Product Management, Design and Marketing, verified to be low-frequency opinion
blogs without daily volume.

At most three of the five *Pflicht* slots may come from one tier, or a busy AI news day would
push his own job out of his own digest.

## Quickstart (after `uv sync`)

```bash
# Prerequisites: Ollama running locally
ollama pull qwen2.5:1.5b            # qwen2.5:7b is usually present already
ollama pull nomic-embed-text        # only needed for stage 2 (threads), not yet built

cp .env.example .env                # then set PULSE_DASH_TOKEN to any long random string

uv run pytest -q                    # gate part 1
uv run ruff check .                 # gate part 2
```

Then, in increasing order of how much CPU they cost:

```bash
# Check every source. Writes data/source_health.json, no model involved.
uv run python scripts/fetch_once.py --survey

# The deterministic funnel: fetch, dedupe, rank. Seconds, no model.
uv run python scripts/run_funnel.py --top 12 --explain

# Measure what the local model costs on this machine. Run it on an IDLE machine —
# see docs/adr/0001-throughput-budget.md for why that matters.
uv run python scripts/bench_ollama.py --quick

# The whole thing. Writes data/digests/<date>.md, and minutes of CPU load.
uv run python scripts/build_digest.py
uv run python scripts/build_digest.py --dry-run        # funnel only
uv run python scripts/build_digest.py --skip-scoring   # skip the 1.5b pass
```

A run that produces nothing usable exits non-zero and writes nothing. That is deliberate: the
previous digest stays the latest one rather than being replaced by something plausible.

The phone side and the daily run:

```bash
(cd frontend && npm ci && npm test && npm run build)   # the PWA, served from frontend/dist
uv run python scripts/serve.py                         # http://127.0.0.1:8430 without a token
bash scripts/install_systemd.sh                        # timer + web service, see docs/ops.md

# Measure the fact check against the labelled sentences (~6 minutes of CPU).
uv run python scripts/eval_faithfulness.py
# The five-day observation table, from the stored digests.
uv run python scripts/observe.py
```

## Stack

Python 3.11+ (uv, ruff, pytest) · FastAPI · SQLite · React + Vite as a PWA · Ollama for
scoring, writing and embeddings. No paid services, no cloud, no API keys.

Everything that touches the network or the model sits behind a seam and is faked in tests, so
the suite never needs connectivity.

## License

MIT — see `LICENSE`.
