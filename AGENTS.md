# AGENTS.md — pulse-scout codebase operations

Read before changing code. Working method and locked decisions: `CLAUDE.md`.
Source of truth for spec/decisions: `PROJECT.md`.

> **State as of 2026-09-20:** phases 1 and 2 are built and live-verified — fetch, cache,
> parse, seen-filter, cluster, rank, score, write, validate, store. `frontend/` and `api.py`
> are the only rows in the table below that do not exist yet. Plan and backlog:
> `docs/superpowers/plans/2026-09-20-pulse-scout-v1.md` and `PLAN.md` (next task: T18/T19).

## Agent stance

- **The pipeline orchestrates; the model is one step inside it, and the last one.** Anything
  that can be decided by code is decided by code — deduplication, engagement ranking, keyword
  matching, thread assignment. The language model only writes prose.
- **Pure logic does not live in adapters, the CLI, or components.** Everything testable lives
  in `src/pulse_scout/core/` and is unit-tested with fixtures and fakes.
- **Two hard lines:** no live network in tests, and no fabricated digest content ever.
- **Throughput awareness is part of correctness here.** Measured on the target machine:
  18,1 tokens/s intake, 4,5 tokens/s generation, CPU only. A change that adds 5.000 tokens of
  context adds ~4,5 minutes to every daily run. Before enlarging a prompt, ask whether the
  same result can come from deterministic code.

## Architecture

| Layer | Directory | Rule |
|---|---|---|
| Fetching | `src/pulse_scout/sources/` | Only place that touches the network. `http.py` is the seam; `collect.py` drives the list and owns the failure policy. |
| Core logic | `src/pulse_scout/core/` | Pure. No network, no Ollama, no filesystem. `canonical`, `dedupe`, `ranking`, `selection`, `validate`, `digest`. |
| Model calls | `src/pulse_scout/llm/` | Only place that talks to Ollama. `ollama.py` is the seam; `scorer`, `writer`, `prompts` sit on top. |
| Storage | `src/pulse_scout/store/` | SQLite. Schema migrations by `PRAGMA user_version` (currently v2). |
| Orchestration | `src/pulse_scout/pipeline.py` | Fetch → seen-filter → cluster → rank, plus the funnel counters. |
| API | `src/pulse_scout/api.py` | **Not built yet (T19).** FastAPI, reads finished digests, **computes nothing.** |
| Frontend | `frontend/` | **Not built yet (T20).** React + Vite, built to static files, served by the API process. |
| CLIs | `scripts/` | Thin. Argument parsing plus a call into the pipeline. |

Config is `data/sources.toml`, read with the standard library `tomllib` — no dependency.

## Run / build / test

```bash
uv sync
uv run pytest -q          # gate part 1
uv run ruff check .       # gate part 2
uv run python scripts/fetch_once.py --survey   # every source once; writes data/source_health.json
uv run python scripts/run_funnel.py --explain  # the deterministic funnel, seconds, no model
uv run python scripts/bench_ollama.py          # throughput — run it on an IDLE machine, see ADR 0001
uv run python scripts/build_digest.py          # the whole pipeline; minutes of CPU
uv run uvicorn pulse_scout.api:app --port 8430 # (planned, T19) the PWA
```

Ollama must be running (`http://localhost:11434`). Models used: `qwen2.5:1.5b` for scoring,
`qwen2.5:7b` for writing, `nomic-embed-text` for threading — the last one needs
`ollama pull nomic-embed-text`.

Port 8430 is chosen to stay clear of equity-scout on 8420 and Airflow on 8080.

## Best first edits

- **Adding a source** → append to `data/sources.toml`. **Fetch the URL first and check the
  body**, not just the status code; several working feeds report `text/html`. The bottom of
  that file lists what is verified broken — don't re-add those without a fresh test.
- **Changing what reaches the Pflicht list** → `core/ranking.py`, not the prompt. Ranking is
  deterministic and testable; the prompt is neither.
- **Changing tone or length of the digest** → the prompt in `llm/writer.py`. Remember every
  100 output tokens cost ~22 seconds of runtime.
- **A source starts failing** → check whether it is marked `fragile` in the config. Fragile
  sources are skipped with a warning; anything else failing is recorded, and if more than 30 %
  of the non-fragile sources fail, the whole run aborts rather than building a digest from a
  crippled funnel.
- **"A source returns nothing"** is usually the 72-hour publication window doing its job, not a
  bug. Most of these feeds are archives: ThoughtWorks Insights returns 2.722 entries back to
  2008 on every call. Check `data/source_health.json` before changing anything.
- **Changing what the model is told about the reader** → `llm/prompts.py`, and build it from
  `PROJECT.md` §3 / decision D7. Spec §1 and §4 still describe a "junior fullstack developer
  specialising in data and BI", which D7 revokes; §4 in particular reads like prose while
  actually specifying the scoring prompt. A test guards against that text coming back.
- **Never widen what the writer may say** without widening `core/validate.py` deliberately.
  Every number in the prose must appear in its source item; that check is the trust promise.
