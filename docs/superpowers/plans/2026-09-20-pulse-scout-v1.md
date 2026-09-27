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

*Written 2026-09-20, at the end of the session that produced this plan.*

### What was built

**Phase 1 complete (T1–T12) and phase 2 complete (T13–T17).** 25 commits on `autopilot/work`,
one per task plus the corrections below; nothing pushed, no remote set. Gate at the end:
**295 tests green, `ruff check .` clean.** Every commit was made on a green gate — with one
exception, recorded below.

Phases 3–5 (T19–T25) are untouched and remain a clean backlog in `PLAN.md`.

### Live verification, not just tests

The funnel was run against all 60 real sources:

```
570 gesichtet → 40 Kandidaten
  570 seen, 559 new, 553 clusters, 40 candidates
  60 sources ok, 0 failed
```

The top candidates were sane without any tuning: an InfoQ Architecture piece and three Azure
PostgreSQL updates reached the top ten on tier 1, a three-source Hacker News/Ars Technica
cluster led on cross-source duplication, and "Tin: full-text search for Postgres" was lifted by
the `postgres` keyword. `data/source_health.json` holds the per-source numbers.

### Deviations from the plan as written

| # | Deviation | Why |
|---|---|---|
| 1 | **T13 was built before T1.** | T1's benchmark needs a client. Building the seam first avoided writing a throwaway HTTP client and then deleting it. |
| 2 | **No cap on cluster size (D-P5 said 8).** | Any cap either discards information or does nothing. The cap that actually matters moved to ranking, where the cross-source bonus stops at four members — so a mega-cluster cannot buy the top slot, and no story is dropped. |
| 3 | **Schema v1 held only the funnel's tables; digests arrived as v2.** | Shipping empty tables whose shape is a guess is worse than migrating once the shape is known — and it meant the migration path was exercised for real before it had to be. |
| 4 | **Items are cut to a 72-hour publication window (new, D9).** | Not in the plan because the plan did not yet know how bad it was. See below. |
| 5 | **`data/digests/` is gitignored.** | The spec permits "our own written digest" in `data/`, but the Kür lines are verbatim third-party headlines and the files are regenerable. The conservative reading of C4 costs nothing. |

### What the live sources forced, and what it cost to find out

Three corrections, each made only after fetching the URL rather than reasoning about it
(`CLAUDE.md`'s rule, and it earned its place three times in one session):

1. **Hacker News was configured to return the wrong twenty items.** `search_by_date?tags=story`
   returns the twenty *newest* submissions — minutes old, one or two points each — so the
   `signal = "points + comments"` the entry declared was empty. The corrected query returned 61
   stories from the last 24 hours, the top one at 490 points. The config's own `note` had
   described the fix; the URL never got it.
2. **All three Nitter mirrors are dead** (connection refused; DNS resolves, nothing listens).
   They were the *primary* coverage for Anthropic, which publishes no RSS at all. Retired into
   the "verified broken" section. Anthropic now rests on GitHub release atoms and aggregators.
3. **The feeds are archives, not news streams.** One call to ThoughtWorks Insights returns
   2.722 entries going back to 2008; OpenAI News returns 1.210 back to 2015; the Azure feed
   returns 200 every time with a BOM in front of the XML declaration. Across the corpus: 5.618
   items older than a week, 367 from the last week, 113 from the last 36 hours. Unwindowed,
   day one ingests 6.193 items and day two ingests them again. A publication window plus the
   persistent seen-set turns that into 570.

### Two corrections to our own work

**A commit went in on a red gate.** A `pytest … | tail -3` pipeline returned `tail`'s exit
status, so `&&` let the commit through with one test failing. Caught within a minute, the test
fixed and the commit amended; every later gate ran under `set -o pipefail`. Recording it
because the iron principle says never commit red, and this session did once.

**The benchmark measured the wrong thing and would have produced the wrong decision.** It
reported a prefix-cache ratio of 0,0 — which would have meant the scoring budget is unreachable
by construction. `prompt_eval_count` reports the full prompt length whether or not the prefix
was cached; a direct probe showed three consecutive calls sharing a 381-token system block all
reporting 381 tokens while intake time fell from 8,43 s to 0,22 s. The cache works; the metric
could not see it. Now measured in time. Full account in `docs/adr/0001-throughput-budget.md`.

**A flaky test suite, found by accident.** Test fixtures derived URLs from `hash(title)`, and
Python randomises string hashing per process — so cluster keys, and every tie-break that falls
back to them, differed between runs. Replaced with a deterministic slug; the suite now passes
under `PYTHONHASHSEED` 0, 1, 2 and 7.

### Findings that stand, and what was done about them

| Finding | Status |
|---|---|
| F1 — the spec still describes the wrong reader, including in the scoring prompt | **Closed in code.** The profile and both prompts are built from D7. A test asserts the system block never says "junior" or "business intelligence" and does name the excluded topics. The spec text itself is unchanged and still wrong; fixing it is Nico's call. |
| F2 — snapshots, not streams | **Closed.** 72-hour window plus the seen-set. |
| F3 — the Hacker News query | **Closed**, verified live. |
| F4 — dead Nitter mirrors | **Closed**, verified live. |
| F5 — the eight-minute budget | **Open.** Measured at 32,3 min, but at load 38–57 on a 16-thread machine shared with other agent sessions. ADR 0001 owes an idle re-measurement before anything is tuned. What the measurement *did* establish: generation, not context, is the bottleneck — which inverts the spec's emphasis. |
| F6 — the uncapped Kür | **Closed.** 15 lines, ≤ 6 per group. |
| F7 — dedupe without a method | **Closed enough.** Conservative, two knobs, every merge records its reason and score so it can be reviewed against reality later. |
| F8 — is the 1.5B pass signal or noise? | **Open by design.** Both ranks and their Spearman correlation are persisted every run. After two weeks there is evidence rather than a belief. |
| F9 — the "why this concerns you" line | **Open, and not engineerable away.** The validator enforces structural honesty. A fluent, confident, wrong relevance claim still passes. It belongs to the five-day verdict. |

### A finding the plan did not have

**Tier 1 is thin.** Over the 72-hour window the live sources returned 22 tier 1 items against
114 tier 2 and 433 tier 3 — his own field is 4 % of the intake. The D8 cap reserves up to three
Pflicht slots for tier 1, but it cannot conjure items that were never published. If the digest
turns out to be mostly tier 2 and 3 in daily use, the answer is more tier 1 sources, not a
different cap. Worth watching during the five-day trial.

### T18 — the first real digest, and what it showed

Run for real against the live sources with `qwen2.5:7b` and `--skip-scoring`. It worked:
`data/benchmarks/2026-09-20-first-run.json`.

```
funnel: 396 gesichtet → 1 Kandidaten in 31s
writing: 156 tokens in 229s
396 gesichtet → 1 für dich · 0:16 Lesezeit
wrote data/digests/2026-09-20.md after 260s total
```

396 fetched items became **one** new one, because this was the second run of the day against
the same sources — the seen-set doing exactly its job. The digest correctly said so on its own
face: *"Ruhiger Tag: nur 1 von 5 Plätzen sind belegt"* and *"Ohne Modell-Bewertung gebaut —
Reihenfolge rein deterministisch."* The quiet-day rule (D-P8) and the honesty notes work.

**And the content is finding F9, on the first try.** The source headline said the companies
face an antitrust suit for agreeing to *slow* AI development. The model wrote that they had
agreed to *stop* it, and supplied a motive ("auf Sicherheitsgründe hin") that appears nowhere
in the source. The "Darum geht's dich an" line read: *"Es könnte deine Arbeit beeinflussen, da
du dich mit Softwarearchitektur befasst"* — true of anything, useful for nothing.

The validator passed it, correctly. Nothing checkable was invented: no numbers, no unknown item
id, no link. Every mechanical guarantee held; the sentence that carries the product still did
not. That is the limit named in F9, now demonstrated rather than predicted, and it is what the
five-day verdict has to decide. It is **not** an argument to reopen D2 — Nico made that call
with the trade-off in front of him — but he should see one real digest before the five days
start, because this is what the local model produces on a quiet Saturday.

Two cheap levers exist before anything structural: the scoring pass was skipped in this run
(so the one candidate reached the writer unfiltered), and the writing prompt has not been
iterated on once. Both are worth trying before drawing conclusions about the model.

### What remains

T19–T25 are open and unstarted: the API and PWA, the timer, the five-day trial, and stage 2.
The session stopped at the phase boundary deliberately — phases 1 and 2 are complete and
verified, and starting a React PWA as the twenty-sixth commit of a long session would have
traded that for something half-built.

### Needs Nico

1. **Git remote and visibility.** Nothing is pushed. Unchanged, and not this agent's call.
2. **Re-run `uv run python scripts/bench_ollama.py` on an idle machine.** Every funnel-sizing
   decision in ADR 0001 waits on it.
3. **Read the spec through** — and decide whether to correct §1 and §4, which still describe a
   "junior fullstack developer specialising in data and BI". The code now ignores them, but the
   next reader of the spec will not know that.
4. **Reddit and CISA from home.** Unchanged. Note that the CISA *KEV JSON* does work from here;
   it was the other CISA endpoints that were blocked.
5. **`ollama pull nomic-embed-text`** before stage 2. Free, ~270 MB, but a local download.

---

## 10 · Outcome, second session (2026-09-27): fact check, phase 3, phase 4

*Written 2026-09-27 by Claude (autonomous session on `autopilot/work`).*

### What was built

11 commits after `ac5b8fe`; nothing pushed, no remote. Gate at the end: **359 pytest green**
(295 before), `ruff check .` clean; frontend **20 vitest green** (none before), `tsc` + `vite
build` clean.

| Task | Commit | What |
|---|---|---|
| T18b (new) | `1ba9259`, `da46c52`, `4ba899b` | Faithfulness guard + labelled eval set + dropped-sentence record |
| — | `87f69ac` | Writer accepts `"[a1]"` — qwen2.5:7b echoed the prompt's brackets on 12 items, which the validator rejected as unknown ids |
| T19 | `2059080`, `4c9a881` | FastAPI read-only API, fail-closed token gate, no loopback exception |
| T20 | `4ccacae` | React 19 + Vite PWA from the mockup |
| T21 | `d64a4e4` | Manifest, icons, module service worker, labelled offline read |
| T22 | `bab3255` | systemd timer 20:30 `Persistent=true`, `daily.sh` (flock, Ollama wait, `--skip-if-built`), web unit, `docs/ops.md` |
| — | `b64db46` | Run stats (incl. D-P9's rank correlation, which was only printed) stored with the digest |
| T23 prep | `00177a7` | Checklist, empty log, `scripts/observe.py` |

### The fact check (T18b) — what it does and what it measured

Every headline and body sentence goes back to `qwen2.5:7b` as a one-word question against the
source text the writer saw. NO or an unreadable answer drops the sentence; nothing is
rephrased. A body with nothing left shows the source's first sentence, marked "Originaltext der
Quelle"; a rejected headline becomes the source title. The digest says how many were dropped
and stores which. "Darum geht's dich an" and the thread are interpretation and stay unchecked.

Labelled set: `data/eval/faithfulness_labels.json`, 119 sentences, no third-party text (sources
by `item_key`, read from the local DB). Kinds: the 2026-09-20 card (3), real writer output
over 12 items (36), hand-written meaning changes (44), and a **held-out** second writer run
over 12 other items (36), labelled and scored only after the prompt was frozen.

| Checker | Unfaithful caught | Faithful dropped | Held-out: caught / dropped | s/sentence |
|---|---|---|---|---|
| 7b, prompt v1 (first 83 labels) | 32/32 | 16/39 | — | 3,0 |
| **7b, prompt v2 (shipped)** | **36/37** | **13/62** (7 of them headlines → source title) | **4/5 · 5/23** | 3,1 |
| 1.5b, prompt v2 | 2/37 | 0/62 | 0/5 · 0/23 | 1,3 |

Interpretation filler inside the body ("Dies könnte … nützlich sein", 20 sentences): all 20
dropped by the 7b checker. The 2026-09-20 failure ("slow" → "stop") is caught.

**How much to trust that.** Optimistic, for three reasons: the labels are Claude's and not
yet reviewed by Nico; the hand-written perturbations come from the same author as the prompt
and are cruder than real errors; and there are only 9 real unfaithful model sentences in the
set. The one untuned number is the held-out row: 4 of 5, with the miss a borderline vendor
claim stated as fact.

**What production showed the same day.** The first scheduled-path run (below) checked 10
sentences and dropped 1 (a headline; which one was not yet recorded — fixed in `4ba899b`). By
Claude's reading of the 9 that shipped, 7 are faithful and 2 are vague distortions that
passed: "Es gibt Diskussionen über die Sichtbarkeit von OpenAI-Inhalten auf Hacker News" for
*OpenAI feared the "optics" of what might appear on Hacker News*, and "AI-Modelle … werden
… verkauft" for *marketplaces selling access to AI models*. The guard stops a changed verb
or an invented claim; it does not stop a vague paraphrase that drifts. That is the honest
limit of a same-size yes/no checker.

**A correction to the first outcome (§9, T18).** The 2026-09-20 card did not invent its
motive: the source summary says the companies agreed to slow development "for safety
reasons". Only "slow" → "stop" was wrong. The headline alone did not carry the reason, which is
probably how the first session read it.

### End to end, for real

`systemctl --user start pulse-scout.service` at 14:01 — the exact path the timer takes — at a
load average of 20–30 from other sessions:

```
funnel: 594 gesichtet → 40 Kandidaten in 30s
scoring: 40 rated in 158s, 0 unparseable, rank correlation 0.70
writing: 547 tokens in 184s (attempt 2)
checking: 10 checked, 1 rejected, 0 cards fell back to the source text, in 67s
594 gesichtet → 5 für dich · 1:32 Lesezeit     — 750 s total
```

Served by `pulse-scout-web.service` on `0.0.0.0:8430`, token-gated (401 without, 200 with, on
localhost, on `<tailscale-ip>:8430` and on `https://<host>.<tailnet>.ts.net:8443` via
`tailscale serve`). Rendered in headless Chromium at 390 px; offline reload shows the stored
digest labelled with its fetch time. **Not verified: a real phone** — that is Nico's first
step. Because today's digest exists, tonight's 20:30 run will skip; the first scheduled build
is 2026-09-28 20:30.

### Deviations from the plan as written

| # | Deviation | Why |
|---|---|---|
| 1 | T18b inserted before T19 | The first digest was wrong in a way no existing check could see; shipping it to the phone first would have put the known bug in Nico's hand. |
| 2 | `pulse-scout-web.service` added in T22 | The plan had `serve.py` but nothing that keeps it running; the phone needs it up. `--require-token` so it cannot start open behind the proxy. |
| 3 | HTTPS on port **8443** via `tailscale serve` (D15) | Service workers and install need a secure context; 443 on this node belongs to equity-scout. |
| 4 | Module service worker, logic in `public/sw-strategy.js` | So the offline decision is unit-tested without a bundler plugin. Needs a Chromium-based browser (Chrome on Android is). |
| 5 | Run stats stored with the digest | D-P9 said "persist"; T14 only printed. T23 needs the numbers. |
| 6 | `httpx2`, not `httpx`, for the TestClient | Starlette 1.7 deprecates httpx and names httpx2. |

### Found, not fixed (named for the next session)

- **The writer ignores "German" for headlines** on longer inputs: all 24 harvested headlines
  were English title fragments (today's 5-card run was mostly German). Prompt work, measured.
- **Body sentence 2 is usually filler** ("Dies könnte … sein"): 20 of 24 harvested cards. The
  fact check drops it, so cards end up one sentence long — shorter, not wrong.
- **The number check rejects German decimals**: "2,8 Sekunden" for a source's "2.8 seconds"
  counts as an invented number, so a correct German sentence can fail a run.
- **Why the writer's first attempt failed today is not logged** — `write_digest` retries
  silently. One line of logging would make attempt-2 runs diagnosable.
- **"Darum geht's dich an" is still generic** (F9): "Du solltest dich für die Diskussionen
  interessieren …". Unchanged by anything here.
- `npm audit`: 2 moderate advisories in vitest's dev-only dependency tree.

### What remains

- **T23** — five days on the phone, Nico's (prepared in `docs/observations/`).
- **T24/T25** — not started, deliberately: stage 2 waits for stage 1 to run daily (§6) and
  for `ollama pull nomic-embed-text`.
