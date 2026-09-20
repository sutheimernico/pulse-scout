# pulse-scout v1 — implementation plan (stage 1, with stage 2 sketched)

**Date:** 2026-09-20 · **Author:** Claude (autonomous session) · **Branch:** `autopilot/work`
**Spec:** `docs/superpowers/specs/2026-08-07-pulse-scout-design.md`
**Binding rules:** `PLAN.md` §Iron principles, `LOOP.md`, `AGENTS.md`, `CLAUDE.md`.

This plan is written to be executed by a fresh agent, one task per iteration. Every task names
its files, its acceptance criteria and its gate. No task leaves a question for the reader —
where the spec is silent or contradictory, this plan decides and says why (§3).

---

## 1 · Context / current state

Phase 0 has been standing since 2026-08-07 and nothing has moved since:

| Item | State |
|---|---|
| Docs | `PROJECT.md`, `PLAN.md`, `LOOP.md`, `AGENTS.md`, `CLAUDE.md`, `README.md`, spec — all written |
| Code | `src/pulse_scout/config.py` only (source-list loader, 17 tests) |
| Config | `data/sources.toml`, 63 entries (44 rss / 14 atom / 5 json), 3 marked fragile |
| Deps | **zero** runtime dependencies; dev = pytest + ruff |
| Gate | green: `uv run pytest -q` → 17 passed, `uv run ruff check .` → clean |
| Backlog | deliberately empty — this document fills it |
| Environment (checked 2026-09-20) | uv 0.11.19, venv on Python 3.13, Ollama up with `qwen2.5:1.5b`, `qwen2.5:7b`, `llama3.1:8b`, `qwen2.5vl:7b`. **`nomic-embed-text` is NOT pulled** (stage 2 blocker, one `ollama pull`). Node v24 present for the PWA. |

Nothing exists between the source list and the screen. Everything below is new.

## 2 · Goal

Stage 1: a real digest, produced by a local pipeline from real feeds, on Nico's phone, every
morning, for free. Acceptance per spec §8: five consecutive days read on the phone without
opening the laptop.

This plan reaches that in four phases (T1–T23) and sketches stage 2 (T24–T25). "Done" for any
task means: gate green, one commit, `PLAN.md` box checked, `AUTOPILOT_LOG.md` line appended.

---

## 3 · Findings on the spec

The brief asked for contradiction rather than agreement. Nine findings, ordered by how much
damage they would have done if built as written. Six are already resolved by decisions in §4;
three stay open as risk.

**F1 — The spec still describes the wrong person, in the one place it reaches the model.**
§1 opens with *"Nico is a junior fullstack developer specialising in data and BI"* — the exact
premise that decision D7 in the same document revokes three pages later. Worse, §4 step [3]
specifies the scoring prompt as *"rates each of the 40 candidates for relevance to a data/BI
developer working in Azure"*. That sentence is not prose, it is the prompt: building it as
written would have scored every candidate against the corrected-away premise, and D7 would
have been silently defeated by a leftover. `PROJECT.md` and `CLAUDE.md` have the corrected
version; the spec was never back-edited. → The relevance profile is built from D7 and
`PROJECT.md` §3, never from spec §1/§4. Also: Nico is not a junior (global CLAUDE.md), and no
prompt in this codebase will say so.

**F2 — Most sources are snapshots, not streams, and the spec has no notion of "already seen".**
Verified live on 2026-09-20 with the configured URLs:

| Source | What one call actually returns |
|---|---|
| Azure service updates RSS | **200 entries every call**, 150 kB, BOM before the XML declaration |
| CISA KEV JSON | **the entire catalogue, 1716 entries**, no "new today" view |
| HuggingFace models | 50 entries every call, by 7-day likes — largely the same 50 tomorrow |
| Lobsters `hottest.json` | the current hot list, heavily overlapping day to day |

Day two of an unguarded pipeline would re-ingest and re-rank the same ~450 items. The spec's
"~400 items in" is a *first-day* number. Dedupe across sources (spec §4 step 2) does not help:
these are duplicates across *time*, not across sources. → A persistent seen-set is not an
optimisation here, it is load-bearing, and it must exist before ranking means anything (D-P2,
T11 ordered before T12).

**F3 — The Hacker News source is configured to return the wrong 20 items.**
`hn.algolia.com/api/v1/search_by_date?tags=story` returns the 20 *newest* submissions, which at
HN's volume is roughly the last twenty minutes, and those have one or two points each. The
entry declares `signal = "points + comments"` — that signal is empty with this URL. Verified
today: the configured URL → 20 hits, `nbHits` 3.765.345, `hitsPerPage` 20. The corrected query
`search?tags=story&numericFilters=created_at_i>{t-24h},points>20&hitsPerPage=100` → 61 stories,
top item 490 points / 194 comments. The config's own `note` describes the fix but the URL never
got it. → Corrected in T8.

**F4 — All three "fragile" sources are dead, and they were the primary Anthropic coverage.**
`nitter.net` was the only instance that worked when the list was built; today `curl` fails to
connect (exit 7, DNS resolves, connection refused) for `/AnthropicAI/rss`, `/claudeai/rss`,
`/OpenAI/rss` and for the site root. Anthropic publishes no RSS at all (spec §7), so its
coverage now rests entirely on GitHub release atoms plus the aggregators. That is thinner than
the spec claims but not fatal. → T8 moves the three entries into the "verified broken" section
with today's date; nothing silently keeps pretending to cover Anthropic.

**F5 — The 8-minute budget mixes a measured number with an unmeasured one.**
18,1 tok/s intake and 4,5 tok/s generation were measured with **qwen2.5:7b**. The write step
checks out against them: ~4k context / 18,1 = 3,7 min plus 700 tokens / 4,5 = 2,6 min ≈ 6,3 min.
The *scoring* step does not: 40 items × ~350 tokens ≈ 14k tokens of intake, which at the 7b rate
is 13 minutes, not the claimed 2. The claim only holds if (a) qwen2.5:1.5b is ~6,5× faster than
qwen2.5:7b on this CPU and (b) Ollama's prefix cache really does retain the shared system block
across 40 consecutive calls. Both are plausible; neither was measured. If either fails, the
daily run is ~20 minutes, not 8. → T1 measures both models and the cache-hit assumption
explicitly, before anything is built on the number. The spec itself calls for this task first.

**F6 — The Kür has no size limit, and the obvious reading breaks the five-minute promise.**
§5 says "one line per item"; after the funnel that is 40 − 5 = 35 lines. D1 says five minutes
buys "12–20 short items total". Both cannot be true. → D-P7: Kür capped at 15.

**F7 — "Dedupe across sources is the strongest importance signal" is asserted with no method.**
Collapsing the same story across 63 heterogeneous feeds is a genuinely hard, tunable problem,
and on day one there is no labelled data to tune against. Anything clever here would be tuned
on vibes. → D-P5 picks the conservative version and records every cluster decision so it can be
reviewed against reality later, instead of pretending it is solved.

**F8 — The 1.5b scoring pass may be noise, and it is the expensive half of the run. (open)**
A 1.5b model producing a 0–10 relevance rating is low-resolution and order-biased, and the
deterministic ranking has already done the hard cut from 400 to 40. The marginal value of
re-ordering 40 down to 12 with a small model is an assumption. Not overridden — D2 and the
funnel are Nico's decisions — but T14 persists the deterministic rank *and* the model rank and
reports the rank correlation, so that after two weeks there is evidence instead of a belief.

**F9 — The one sentence that carries the whole product is the one a 7B CPU model writes worst. (open)**
"Darum geht's dich an" is the product. It is also exactly where a small model bluffs most
convincingly. The honesty rule ("no fabricated digests") is enforceable for *structure* —
T16 rejects any judgement referencing an unknown item, any invented URL, and any number in the
prose that does not appear in the source item. It is not enforceable for a fluent, confident,
wrong relevance claim. That residual risk cannot be engineered away and belongs to the
five-day verdict, not to a validator.

**Minor:** `AUTOPILOT_LOG.md` says "~90 feeds" verified, `data/sources.toml` has 63 —
the log overstates. Not worth a task; corrected in passing when the log is next appended to.

---

## 4 · Decisions this plan makes (default + reason)

| # | Decision | Reason |
|---|---|---|
| D-P1 | **Phases 1–2 add zero runtime dependencies.** `urllib.request`, `xml.etree.ElementTree`, `json`, `sqlite3`, `tomllib`. FastAPI + uvicorn enter only in Phase 3, as the spec requires them. | The project already made this choice for the config ("TOML so the config costs no dependency"). `feedparser` is a large dependency for what ElementTree does in 40 lines; `httpx` buys async we do not need for 63 sequential requests once a day. |
| D-P2 | **Persistent seen-set, keyed by `item_key`** = canonical URL, falling back to `sha1(source_name + guid)` when there is no URL. An item enters the funnel only the first time it is seen; re-sightings only bump `last_seen`. | F2. Without it the funnel re-processes ~450 snapshot items every day. |
| D-P3 | **HN query corrected** to `search?tags=story&numericFilters=created_at_i>{t-24h},points>20&hitsPerPage=100`. | F3, verified live today. |
| D-P4 | **CISA KEV filtered by `dateAdded` inside the window**, not by feed position. | F2 — the endpoint has no "new" view. |
| D-P5 | **Dedupe = canonical-URL identity, then normalised-title token-set Jaccard ≥ 0,60 within a 48 h window**, single-link agglomeration, cluster capped at 8 members. Every cluster stores its members and the reason it merged. | F7. Cheap, deterministic, explainable, reviewable. Two knobs, both in `data/profile.toml`. |
| D-P6 | **Ranking is one explicit formula**, all constants in `data/profile.toml`: `score = source_weight · tier_bonus · (1 + k_eng·log1p(engagement_pct)) · (1 + k_kw·keyword_hits) · recency_decay · (1 + k_dup·(cluster_size − 1))`. Engagement is normalised *within* its source (HN points and HF likes are not comparable). | Every knob visible, diffable and unit-tested; no hidden heuristics. |
| D-P7 | **Funnel sizes: 40 candidates → 12 finalists → up to 5 Pflicht + up to 15 Kür.** Kür grouped by tier/topic, max 6 per group. | F6; keeps D1's "12–20 items" true and the five-minute promise honest. |
| D-P8 | **Quiet days stay quiet.** Pflicht is *up to* five: a finalist below `min_pflicht_score` does not get a slot, and the header states how many qualified. | Honesty rule. Filling a slot to reach five is fabrication with extra steps. |
| D-P9 | **Both rankings are persisted** (deterministic rank, model rank) plus their Spearman correlation per run. | F8 — turns an assumption into a measurement at near-zero cost. |
| D-P10 | **Writer output is one JSON object**, every judgement carrying `item_id`. Validation rejects unknown ids, URLs not present in the input, and any number in the prose that does not occur in that item's title or summary. A failed validation **fails the run**; the previous digest remains the latest. | The honesty rule made mechanical. A visible failure is the specified behaviour. |
| D-P11 | **Digest date = the Europe/Berlin date of the run.** The run is in the evening; the UI shows the date plus `Stand HH:MM`. No digest is ever labelled with a date it was not produced on. | Avoids inventing a "tomorrow" label for content gathered today. |
| D-P12 | **Read time is computed, not guessed**: `words / 200 wpm + 3 s per Kür line`, rounded up. Above 5:30 the build logs a budget warning (not an error). | C5 becomes checkable instead of aspirational. |
| D-P13 | **Fail-closed access**: `scripts/serve.py` binds `127.0.0.1` when `PULSE_DASH_TOKEN` is empty and `0.0.0.0` only when it is set; when a token is configured the app rejects every `/api/*` request without it. | Binding is the only real protection; a token check on a `0.0.0.0` bind with an empty token is theatre. |
| D-P14 | **Test fixtures are hand-written synthetic feeds**, never captured third-party bodies — not even in `tests/`. | C4. `.cache/` is gitignored for this reason; a fixture is a commit. |
| D-P15 | **Model choice stays as specified**: `qwen2.5:1.5b` scoring, `qwen2.5:7b` writing, `nomic-embed-text` embeddings. `llama3.1:8b` is present on the machine but is not used — one more model would mean one more load/unload cycle per run on a 15 GB box. | D2; and RAM churn is a real cost on CPU-only inference. |

---

## 5 · Target layout

```
src/pulse_scout/
  config.py          existing — source list
  profile.py         relevance profile + ranking constants (data/profile.toml)
  models.py          Item, Cluster, Candidate, Judgement, Digest — pure dataclasses
  sources/
    http.py          THE network seam: Fetcher protocol, UrllibFetcher, FetchResult
    cache.py         .cache/raw/<date>/<slug> — write/read raw bodies (gitignored)
    feeds.py         RSS + Atom → Item, body sniffing, BOM tolerance
    json_api.py      HuggingFace / HN / Lobsters / CISA adapters
    collect.py       drives all sources, fragile handling, FetchReport
  core/
    canonical.py     URL canonicalisation + item_key
    dedupe.py        clustering
    ranking.py       the D-P6 formula
    selection.py     finalists, Pflicht cap (D8), Kür cap (D-P7)
    validate.py      the honesty validator (D-P10)
    digest.py        assembly + markdown render + read-time
  llm/
    ollama.py        THE model seam: Client protocol, OllamaClient, timings
    prompts.py       all prompt text in one file
    scorer.py        1.5b relevance pass
    writer.py        7b digest pass
  store/
    db.py            SQLite schema, PRAGMA user_version migrations
    repo.py          queries (seen-set, runs, digests)
  pipeline.py        orchestration + funnel counters
  api.py             FastAPI (phase 3) — reads, computes nothing
frontend/            React + Vite PWA (phase 3)
scripts/             bench_ollama.py · fetch_once.py · run_funnel.py · build_digest.py · serve.py
data/                sources.toml · profile.toml · benchmarks/ · source_health.json
```

---

## 6 · Tasks

Gate for **every** task: `uv run pytest -q` green **and** `uv run ruff check .` clean, then one
Conventional Commit. No task may commit raw feed text.

### Phase 1 — the deterministic funnel (no model)

**T1 · Measure the model before designing around it**
*Files:* `scripts/bench_ollama.py`, `data/benchmarks/<date>-ollama-throughput.json`, `docs/adr/0001-throughput-budget.md`
The spec names this as task one. Measure, on this machine, with synthetic prompts of the
designed shapes (a scoring prompt of ~350 tokens × 40 calls; a writing prompt of ~4.000 tokens
with a 700-token cap): prompt intake tok/s and generation tok/s for **both** `qwen2.5:1.5b` and
`qwen2.5:7b`, and whether Ollama's prefix cache holds across 40 consecutive scoring calls
(compare call 1 against calls 2–40 via `prompt_eval_count`/`prompt_eval_duration`).
*Acceptance:* the JSON records real measured numbers with the model tags and the machine; the
ADR states the resulting daily budget and, if it exceeds 12 minutes, which of finalist count,
output cap or candidate count shrinks. Prompt text is synthetic and labelled as such — no feed
content. *Test:* the script's pure parts (token accounting, report shaping) are unit-tested with
a fake client; the live run is manual and its output committed.

**T2 · Item model and canonical keys**
*Files:* `src/pulse_scout/models.py`, `src/pulse_scout/core/canonical.py`, `tests/test_canonical.py`
Frozen dataclasses `Item` (source_name, tier, title, url, summary, published_at, engagement,
raw_id) and `Cluster`. `canonical_url()` lowercases the host, drops `utm_*`/`ref`/`fbclid`,
strips a trailing slash and `#fragment`, unwraps `m.`/`amp.` hosts and Google-News style
redirect wrappers. `item_key()` = canonical URL, else `sha1(source|guid)`.
*Acceptance:* round-trip table of ≥ 12 URL pairs that must and must not collapse.

**T3 · The network seam**
*Files:* `src/pulse_scout/sources/http.py`, `tests/test_http.py`
`Fetcher` protocol → `FetchResult(url, status, body: bytes, headers, elapsed_s, error)`.
`UrllibFetcher`: configured `PULSE_USER_AGENT`, 20 s timeout, gzip, conditional GET via stored
ETag/Last-Modified, one retry on a transport error, a per-host minimum interval, and no
exceptions escaping — failures come back as `FetchResult.error`. No test touches the network:
the transport is injected.
*Acceptance:* tests cover 200 / 304 / 404 / timeout / connection-refused, the UA header, and
that a failure never raises.

**T4 · Raw cache**
*Files:* `src/pulse_scout/sources/cache.py`, `tests/test_cache.py`
Write bodies to `.cache/raw/<YYYY-MM-DD>/<source-slug>.<ext>`, read them back, prune older than
14 days. A guard rejects any path that resolves outside `.cache/`.
*Acceptance:* a test asserts the cache root is inside `.cache/` and that writing under `data/`
raises. Gitignore already covers it; the test is the second lock.

**T5 · RSS and Atom parsing**
*Files:* `src/pulse_scout/sources/feeds.py`, `tests/test_feeds.py`, `tests/fixtures/*.xml`
Sniff the body, not the header (LOOP.md): strip BOM and leading whitespace, accept `<?xml`,
`<rss`, `<feed`; reject anything starting `<!DOCTYPE html` or `<html` with a clear error.
Parse RSS 2.0 (`item/title|link|description|pubDate|guid`) and Atom
(`entry/title|link[@rel=alternate]|summary|content|updated|id`) with ElementTree, namespace-
agnostic by local tag name. Dates: RFC 822 and ISO 8601, both to aware UTC; unparseable date →
`None`, never `now()`.
*Acceptance:* fixtures — hand-written, synthetic (D-P14) — for RSS, Atom, BOM-prefixed XML,
an HTML page, malformed XML, an entry without a date. A source that fails to parse yields an
error, never a partial silent result.

**T6 · JSON adapters**
*Files:* `src/pulse_scout/sources/json_api.py`, `tests/test_json_api.py`
One adapter per JSON source, selected by URL host+path: HuggingFace models (`likes`,
`downloads`, `modelId`, `createdAt`), HF daily papers (`paper.upvotes`, title, summary),
HN Algolia (`points`, `num_comments`, dead-link fallback to the HN item URL), Lobsters
(`score`, `comment_count`), CISA KEV (filter `dateAdded` to the window per D-P4).
*Acceptance:* synthetic payloads per adapter, including an unknown-shape payload, which must
raise rather than produce empty items.

**T7 · The collector**
*Files:* `src/pulse_scout/sources/collect.py`, `tests/test_collect.py`
Walk the source list, fetch, cache, parse, normalise. `fragile = true` → warning and skip.
Non-fragile failure → recorded error; if more than 30 % of non-fragile sources fail the whole
run fails loudly (a half-empty funnel silently producing a digest is the failure mode the
honesty rule exists to prevent). Returns `FetchReport` with per-source status, item counts,
elapsed time.
*Acceptance:* tests with a fake fetcher for the all-green, one-fragile-down, one-hard-down and
mass-failure cases.

**T8 · First live fetch and the source reality check**
*Files:* `scripts/fetch_once.py`, `data/source_health.json`, `data/sources.toml` (corrected)
Run the collector against the real list once, respecting the limits. Write per-source health
(status, item count, parse result) to `data/source_health.json` — derived data, committable.
Apply F3 (HN query) and F4 (three dead nitter entries → "verified broken", dated 2026-09-20)
plus whatever else the run proves dead. Every change to the list is preceded by a real fetch
of that URL (CLAUDE.md).
*Acceptance:* `source_health.json` holds real numbers from a real run; no raw body is
committed; `test_real_source_list_is_valid` still passes.

**T9 · Clustering**
*Files:* `src/pulse_scout/core/dedupe.py`, `tests/test_dedupe.py`
D-P5. Normalise titles (casefold, strip punctuation, drop a stopword list, drop a leading
source prefix like `Show HN:`), token-set Jaccard, 48 h window, single-link, cap 8. Each
cluster keeps its members and a merge reason.
*Acceptance:* a table of realistic title pairs (same story across sources; same words different
story) with the expected verdict, plus a stability test: clustering is order-independent.

**T10 · Relevance profile and ranking**
*Files:* `data/profile.toml`, `src/pulse_scout/profile.py`, `src/pulse_scout/core/ranking.py`, `tests/test_ranking.py`
The keyword profile is built from `PROJECT.md` §3 / D7 — FastAPI, SQLModel, SQLAlchemy,
Alembic, PostgreSQL, Pydantic, React 19, TypeScript, Vite, Tailwind, React Aria, Recharts,
Azure Container Apps/Functions/Key Vault, Pulumi, Azure DevOps, Sentry, OpenTelemetry, Docker,
architecture terms, the named labs — with explicit negative terms for the excluded topics
(dbt, Databricks, Terraform, Kubernetes, SQL Server). **Never from spec §1/§4** (F1).
Ranking is the D-P6 formula; output is the top 40 candidates.
*Acceptance:* the formula is tested term by term (each factor changes the order in the expected
direction); a negative-term item is demoted; the profile file is the only place constants live.

**T11 · Storage**
*Files:* `src/pulse_scout/store/db.py`, `src/pulse_scout/store/repo.py`, `tests/test_store.py`
SQLite, schema v1 via `PRAGMA user_version`: `items` (item_key unique, first_seen, last_seen,
source, tier, title, url, summary, published_at, engagement_json), `clusters`, `cluster_items`,
`runs` (funnel counters, timings), `scores`, `digests`, `digest_items`. Idempotent upsert on
`item_key` (D-P2). A migration test proves v0 → v1 on an empty file and that re-running is a
no-op.
*Acceptance:* new-vs-seen behaviour is tested explicitly: the same item twice yields one row and
one funnel entry.

**T12 · Phase-1 pipeline**
*Files:* `src/pulse_scout/pipeline.py`, `scripts/run_funnel.py`, `tests/test_pipeline_funnel.py`
collect → normalise → seen-filter → cluster → rank → persist run, with real funnel counters
(`seen`, `new`, `clustered`, `candidates`). No model involved. The script prints the funnel line
the header will later show.
*Acceptance:* an end-to-end test with a fake fetcher and a temp DB asserts the counters, and
asserts that a second run over the same feed produces zero new items.

### Phase 2 — the model and the digest

**T13 · The model seam**
*Files:* `src/pulse_scout/llm/ollama.py`, `tests/test_ollama.py`
`Client` protocol: `generate(model, prompt, system, options) -> Completion` and
`embed(model, text) -> list[float]`, `Completion` carrying text plus Ollama's token counters and
durations. `OllamaClient` over `urllib` against `OLLAMA_HOST`, `num_ctx`/`num_predict`/
`temperature=0.2` explicit, long timeouts (a 7b CPU write takes minutes), non-streaming.
Connection refused → a clear "is Ollama running?" error. `FakeClient` lives in `tests/`.
*Acceptance:* tests cover a scripted response, a refused connection, a truncated response and
timing extraction. No test reaches the network.

**T14 · Scoring pass**
*Files:* `src/pulse_scout/llm/prompts.py`, `src/pulse_scout/llm/scorer.py`, `tests/test_scorer.py`
One short prompt per candidate, byte-identical system block across calls so the prefix cache can
hold (F5). Output contract: a single integer 0–10 on the first line, optional short reason on
the second. Unparseable output → score `None`, the candidate keeps its deterministic rank, and
the run records the parse-failure count — never a guessed number. Persist both ranks and the
Spearman correlation (D-P9).
*Acceptance:* tests for clean output, chatty output, no number at all, out-of-range; and that
the system block passed to the client is identical across calls.

**T15 · Selection**
*Files:* `src/pulse_scout/core/selection.py`, `tests/test_selection.py`
Top 12 finalists by combined rank. Pflicht: up to 5, hard cap 3 per tier (D8), minimum score
(D-P8). Kür: up to 15 from the remaining candidates, ≤ 6 per group, grouped by tier/topic.
Pure function, no I/O.
*Acceptance:* the cap is tested with an input where one tier owns the top five (expect 3 + 2);
the quiet-day case yields fewer than five and says so; Kür never exceeds 15.

**T16 · Writer and the honesty validator**
*Files:* `src/pulse_scout/llm/writer.py`, `src/pulse_scout/core/validate.py`, `tests/test_writer.py`, `tests/test_validate.py`
One call: 12 finalists in (id, title, source, summary trimmed to a budget), one JSON object out —
`{"judgements":[{"item_id","headline","body","why_you"}...],"thread":"..."}`, `num_predict`
capped per T1's budget. The validator (D-P10) rejects: unknown `item_id`, a duplicate id, any
URL in the prose, any digit-group in the prose absent from that item's title+summary, an empty
`why_you`, a body over the length budget. Failure raises `DigestRejected`; the caller does not
retry more than once and then fails the run.
*Acceptance:* a fake client that hallucinates an item id, one that invents a number, one that
returns prose instead of JSON, and one clean response — the first three must fail the run.

**T17 · Digest assembly and the CLI**
*Files:* `src/pulse_scout/core/digest.py`, `scripts/build_digest.py`, `tests/test_digest.py`
Assemble `Digest` (date per D-P11, funnel counters, Pflicht judgements, thread, Kür lines,
read-time per D-P12), persist it, render Markdown to `data/digests/<date>.md`. `build_digest.py`
runs the whole pipeline; a failed validation exits non-zero and leaves yesterday's digest as
the latest.
*Acceptance:* a full fake-client run produces a Markdown file whose every headline traces to an
input item; the read-time estimate is asserted; a rejected run writes nothing.

**T18 · The first real digest, measured**
*Files:* `data/benchmarks/<date>-first-run.json`, `AUTOPILOT_LOG.md`
Run it for real against live feeds and the real models. Record wall-clock per stage, funnel
counters, parse-failure count, and whether the T1 budget held.
*Acceptance:* real numbers from a real run, committed. If the run exceeds the T1 budget, the
ADR from T1 is updated and the finalist/output caps shrink — in that order.

### Phase 3 — API and PWA

**T19 · API**
*Files:* `src/pulse_scout/api.py`, `scripts/serve.py`, `tests/test_api.py`, `pyproject.toml`
FastAPI + uvicorn enter here (the first new dependencies; justified by the spec's stack).
`GET /api/digest/latest`, `/api/digest/{date}`, `/api/digests` (dates only), `/api/health`
(last run, funnel counters, source health). Reads only — computes nothing (AGENTS.md).
Token gate and binding per D-P13. Mounts `frontend/dist` when present.
*Acceptance:* TestClient covers no-token-configured → loopback-only and open API;
token-configured → 401 without it, 200 with it; unknown date → 404, never an empty shell.

**T20 · PWA**
*Files:* `frontend/*` (Vite + React 19 + TypeScript, vitest), `frontend/src/*`
Built from `mockup/index.html`, which Nico already approved. Sections: header with date,
read-time and the real funnel count; Heute (up to 5 cards with the set-off "Darum geht's dich
an"); Roter Faden; Kür collapsed and grouped. German UI. Sample data, if ever shown, is
labelled as sample data.
*Acceptance:* `npm run build` succeeds; vitest covers the pure formatting helpers; the funnel
count renders the API's numbers and never a placeholder.

**T21 · Offline and install**
*Files:* `frontend/public/manifest.webmanifest`, `frontend/public/sw.js`, `frontend/public/icons/*`
Add-to-home-screen, and the last fetched digest readable offline (cache-first for the shell,
network-first with cache fallback for `/api/digest/latest`). An offline read is labelled with
its timestamp so a stale digest can never look like today's.
*Acceptance:* manifest validates; a vitest unit test covers the cache-fallback decision.

### Phase 4 — operation

**T22 · Timer and catch-up**
*Files:* `scripts/daily.sh`, `deploy/pulse-scout.service`, `deploy/pulse-scout.timer`, `docs/ops.md`
systemd user timer, evening run, `Persistent=true` so a laptop that was asleep catches up.
`daily.sh` is idempotent: if today's digest already exists it exits 0 without burning 8 minutes
of CPU.
*Acceptance:* `docs/ops.md` documents install, logs and the manual run; the idempotence check is
unit-tested in the pipeline layer.

**T23 · Five-day observation**
*Files:* `docs/observations/<date>-five-days.md`
Log per day: funnel counters, runtime, parse failures, scorer/deterministic rank correlation,
and Nico's verdict. This is the stage-1 acceptance evidence.
*Acceptance:* five real days. **Needs Nico** for the verdict column.

### Phase 5 — stage 2 (threads), only after stage 1 has run

**T24 · Embeddings and thread assignment** — `src/pulse_scout/llm/embedder.py`,
`src/pulse_scout/core/threads.py`, store tables, cosine similarity with a threshold, day
counters. Blocked on `ollama pull nomic-embed-text`.

**T25 · "Läuft weiter" in the UI and the Sunday arc** — the thread section with day counters,
and one weekly summary view.

---

## 7 · Verification (definition of done for stage 1)

1. `uv run pytest -q` green and `uv run ruff check .` clean — per task, not only at the end.
2. `git log --oneline` shows one atomic Conventional Commit per task, none on `main`.
3. `uv run python scripts/fetch_once.py` completes against the real list and
   `data/source_health.json` holds real numbers.
4. `uv run python scripts/build_digest.py` produces `data/digests/<date>.md` in which every
   headline traces back to a real fetched item, and the funnel counters are the real ones.
5. A deliberately hallucinating fake writer makes the run **fail** — verified by test, not by
   inspection.
6. `git status` shows nothing under `.cache/` and no raw feed body anywhere in the diff.
7. `uv run python scripts/serve.py` with an empty `PULSE_DASH_TOKEN` binds loopback only;
   with a token set, `/api/digest/latest` is 401 without it.
8. Five consecutive days read on the phone (T23) — the spec's acceptance criterion, and the
   only one this plan cannot verify by itself.

## 8 · Needs Nico (unchanged, plus one)

- **Git remote and visibility.** Nothing is pushed. Not this agent's call.
- **Reddit and CISA from home** — the IP-block hypothesis still untested from the home network.
  (The CISA *KEV JSON* does work from here; it is the other CISA endpoints that were blocked.)
- **Five-day verdict** after stage 1.
- **New:** `ollama pull nomic-embed-text` before Phase 5 — free, ~270 MB, but a local download.

## 9 · Outcome

*(appended at the end of the session)*
