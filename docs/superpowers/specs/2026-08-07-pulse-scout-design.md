# pulse-scout — Design (Spec)

**Status:** approved in the brainstorming session of 2026-08-07, pending Nico's read-through.
**Author:** Claude, in dialogue with Nico.
**Supersedes:** nothing. First spec for this project.

---

## 1 · What this is

A daily digest of the AI and tech world, read on a phone in five minutes. Its job is not to
show Nico everything that happened — it is to throw away 99% of what happened and present the
remainder in a form that makes him better at his work.

Nico is a junior fullstack developer specialising in data and BI, working in an Azure
environment. He has at most five minutes a day. He wants two things at once: to stay broadly
aware of the tech world, and to get genuinely better at his own field. The design resolves that
tension with a two-tier structure — a short *Pflicht* section with real substance, and a *Kür*
section that exists only so a name has been read once.

**Non-goal:** completeness. **Non-goal:** being a news reader with a feed. **Non-goal:**
anything that costs money to run.

---

## 2 · Hard constraints (not negotiable without a new spec)

| # | Constraint | Where it comes from |
|---|---|---|
| C1 | **No running costs, ever.** No paid APIs, no paid cloud, no subscriptions. | Nico's standing rule for private projects; enforced by the guard hook |
| C2 | **The digest is written by a local model.** Nico chose this explicitly on 2026-08-07 after being shown the measured cost and quality trade-off against the Claude API. | Decision D2 |
| C3 | **Runs on Nico's laptop.** No GPU available inside WSL — Ollama runs on the CPU (i7-1360P, 16 threads, 15 GB RAM). | Measured 2026-08-07 |
| C4 | **Third-party feed content is never committed.** Raw article text is someone else's copyrighted work; it lives in `.cache/` and is gitignored. Only derived data (ids, urls, scores, our own written digest) goes into `data/`. | Same rule as match-scout |
| C5 | **Five minutes means five minutes.** Any feature that grows the daily read time needs an explicit decision. | The whole premise |

### The measurement that drives the architecture

Measured on the target machine with `qwen2.5:7b`, a realistic 6.318-token digest prompt:

| | measured |
|---|---|
| Prompt intake | **18,1 tokens/s** (6.318 tokens took 5,8 minutes) |
| Generation | **4,5 tokens/s** |

Every context token costs ~55 ms and every output token ~220 ms. **Context length and output
length are the scarcest resources in the system.** A naive design that hands 40 candidates
(~20k tokens) to the model and asks for a 3.000-token digest would take about 30 minutes of
full CPU load per day. The architecture in §4 exists to bring that down to roughly 8 minutes.

---

## 3 · Topics

Reordered on 2026-08-07 after Nico clarified what he actually cares about (decision D5).

**Tier 1 — AI models and releases.** The core interest: what came out, and is it stronger?
Anthropic (including feature announcements), OpenAI, DeepSeek, Kimi/Moonshot, Qwen, Mistral,
MiniMax. This is the category that gets the most Pflicht slots.

**Tier 2 — Azure and cloud.** Nico works in a large cloud environment; Azure product updates
are directly job-relevant.

**Tier 3 — everything else with real daily volume.** Development, DevOps, Security,
Hardware/IT, Crypto/Fintech, Founders.

**Explicitly excluded:**

| Excluded | Reason |
|---|---|
| Product Management, Design, Marketing | Verified 2026-08-07: these are near-exclusively low-frequency opinion blogs (monthly), not news. A *daily* digest would be empty most days. Nico chose to drop them entirely rather than fake volume. |
| dbt specifically, and the data-tooling blog ecosystem around it | Nico: "dbt muss ich gar nicht wissen, das ist nicht mein Teil." Data topics still arrive, but through Azure (Fabric, Synapse, SQL) rather than the tool vendors. |

Dropping the first group had a useful side effect: Reddit is unusable as a source (verified —
it blocks unauthenticated server access), and Reddit was the *only* relevance signal available
for exactly those topics. Their removal makes the Reddit loss harmless.

---

## 4 · Architecture — a funnel where the model comes last

```
  ~400 items                40 candidates          12 finalists         the digest
      │                          │                      │                    │
  [1] fetch  ──────────►  [2] dedupe+rank  ─────►  [3] score  ─────►   [4] write
   RSS/APIs               no model, ms             1.5b, ~2 min        7b, ~6 min
```

**[1] Fetch — no model, seconds.** RSS/Atom feeds and open JSON APIs, all free and
key-less. Raw responses land in `.cache/raw/` (gitignored). The fetcher must inspect content
rather than trust the server's declared content type — several verified feeds report
`text/html` while returning valid XML.

**[2] Dedupe and rank — no model, milliseconds.** The same story appears in five sources;
collapsing those into one item is simultaneously the strongest importance signal available.
Combined with built-in engagement numbers (Hacker News points, Lobsters score, HuggingFace
downloads and likes) and a keyword profile of Nico's work, this cuts ~400 to ~40 without any
inference at all.

**[3] Score — the small model, ~2 minutes.** `qwen2.5:1.5b` rates each of the 40 candidates
for relevance to a data/BI developer working in Azure. One short prompt per item so the shared
system portion stays in the model's cache instead of being re-read 40 times.

**[4] Write — the 7B model, ~6 minutes.** Only the top 12 go in (~4k context), and only ~700
tokens come out: five short judgements plus the connecting thread. The Kür lines below are
titles straight from step 2 and need no model at all.

The ~8 minute total is extrapolated from the §2 measurement, not measured end-to-end.
**Measuring it for real is the first task in the implementation plan** — if it lands far above
that, the finalist count and output budget shrink before anything else changes.

### Threading — connections without the language model

"Understanding how things connect" is the criterion Nico rated highest and the one a 7B model
would handle worst. So it is solved without one. Each item gets an **embedding**
(`nomic-embed-text`, ~270 MB); a new item is attached to an existing thread by cosine
similarity or opens a new one. Deterministic, milliseconds, and reliable for "is this the same
topic?". The language model then only writes one sentence about a thread the code hands it
fully assembled — it never has to hold weeks of history together itself.

---

## 5 · What the screen shows

Validated against a clickable mockup on 2026-08-07; Nico confirmed the density.

| Section | Content |
|---|---|
| **Header** | Date, estimated read time, and the funnel count (`412 gesichtet → 5 für dich`) — the filter ratio is the product's actual promise, so it is visible |
| **Heute** | 5 cards: headline, two sentences, and a set-off "Darum geht's dich an" line |
| **Roter Faden** | Two sentences connecting the day |
| **Läuft weiter** | *(stage 2)* active threads with a day counter, one line each |
| **Kür** | One line per item, grouped by topic, collapsed |

UI language is German; code, identifiers and commits are English.

---

## 6 · Stack

Same shape as equity-scout, which already runs this pattern in production on Nico's machine.

- **Pipeline:** Python 3.11+, uv, no web dependencies. Pure and unit-testable.
- **Storage:** SQLite. Raw cache on disk, gitignored.
- **API:** FastAPI, reads finished digests only — it never computes anything.
- **Frontend:** React + Vite as a PWA, served as static files by the same process.
- **Access from the phone:** shared-secret token gate, "add to home screen", Tailscale when
  out of the house. Without a token the server binds to loopback only (fail-closed).
- **Scheduling:** systemd user timer, evening run, catching up missed runs. WSL sleeps with
  Windows, so a fixed night-time slot would silently skip days.

Every network call and every model call sits behind a seam and is faked in tests. No test ever
touches the network.

---

## 7 · Sources

The verified source list lives in `data/sources.toml` (all entries confirmed by live fetch on
2026-08-07; anything that answered with HTML instead of a feed was dropped, and is listed at
the bottom of that file so nobody re-adds it). TOML rather than YAML because Python 3.11 reads
it from the standard library, so the config costs no dependency. Highlights:

- **Model strength, with hard numbers:** `https://huggingface.co/api/models?sort=likes7d` —
  downloads and likes per model. This is "which models are strong" as a measurement rather
  than a claim. Sorting by creation date instead is useless: it returns hobbyist uploads with
  zero downloads.
- **Anthropic announcements:** Anthropic publishes **no RSS feed**. Covered three ways so no
  single failure kills the category: a Nitter mirror of `@AnthropicAI` and `@claudeai`, GitHub
  release feeds (`https://github.com/<org>/<repo>/releases.atom`), and the aggregators.
  **Nitter is fragile** — of four instances tested, only `nitter.net` worked. Treat it as a
  bonus, never a foundation.
- **Azure:** `https://www.microsoft.com/releasecommunications/api/v2/azure/rss` — 200 current
  entries, covers Fabric, Synapse and Databricks too. Note the widely-cited
  `azure.microsoft.com/updates/feed/` does **not** work; it returns HTML.
- **Any Microsoft gap:** `https://learn.microsoft.com/api/search/rss?search=<term>` returns a
  valid feed for an arbitrary search term — this covers Power BI, whose own blog is blocked.
- **Relevance signals:** Hacker News (Algolia), Lobsters, Dev.to all expose points/score and
  comment counts for free without a key.

---

## 8 · Stages and acceptance

**Stage 1 — the daily digest.** Fetch, dedupe, score, write, PWA, timer. Done when Nico reads
a real digest on his phone for five consecutive days without opening a laptop.

**Stage 2 — threads.** Embeddings, thread assignment, day counters, the Sunday arc. Done when
a thread correctly links a story across at least three non-consecutive days. Stage 2 needs
several weeks of accumulated history before it can connect anything, so it cannot be evaluated
early.

### Deliberately out of scope for now

**A feedback channel** (thumbs up/down, a "try this later" list). It would help, but it
requires daily typing, which contradicts the five-minute promise. Revisit after stage 2 has
run for four weeks.

**A spoken version of the digest** — Nico raised this on 2026-08-07: five to ten minutes of
audio to listen to on the move instead of reading. Recorded as task #1 rather than built,
because it should only be attempted once the written digest has proved itself in daily use.
The numbers are workable: five to ten minutes of speech is 1.000–2.000 tokens, so four to
seven minutes of generation at the measured rate, plus one to two minutes for local
text-to-speech (Piper — free, offline, German voices, faster than real time). That roughly
doubles the daily compute. Two things to get right when the time comes: spoken text is not
the reading text and needs its own pass (no bullet points, no parentheses, abbreviations
spelled out), and the likely delivery route is a private RSS feed so it lands in a normal
podcast app rather than in the PWA.

---

## 9 · Decisions (dated, closed)

| # | Date | Decision | Rationale |
|---|---|---|---|
| D1 | 2026-08-07 | Two-tier digest: Pflicht with substance, Kür as one-liners | Five minutes buys 12–20 short items total; spreading them evenly across topics would make everything shallow |
| D2 | 2026-08-07 | The digest is written locally by Ollama, not by the Claude API | Nico chose this after seeing the measured comparison (~30 min CPU vs ~8 s and ~3 €/month). Cost avoidance outweighs quality here. **Claude was against it and said so twice; the decision stands.** |
| D3 | 2026-08-07 | Threading via embeddings, not via the language model | Plays to the local model's weakest area; embeddings are deterministic and fast |
| D4 | 2026-08-07 | PWA in the equity-scout pattern, not a native app | The pattern already runs on Nico's machine; no build cycle, no store |
| D5 | 2026-08-07 | Topic set narrowed: AI models first, Azure second; Product/Design/Marketing and dbt dropped | Nico's explicit correction plus the verified finding that the dropped topics have no daily volume |
| D6 | 2026-08-07 | Build stage 1 first, then stage 2 on top | Stage 2 needs weeks of history before it does anything; stage 1 produces that history |

---

## 10 · Needs Nico

- **Git remote and visibility.** Nothing is pushed anywhere until Nico decides. Note that the
  source list and the digests themselves contain no personal data, so this could be public.
- **Test Reddit and CISA from home.** Both fail from this environment with what looks like an
  IP block rather than a missing key. Reddit would add a relevance signal; the CISA advisory
  feeds would strengthen the security category. Neither is load-bearing.
- **Read-through of this spec** before the implementation plan is written.
