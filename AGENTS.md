# AGENTS.md — pulse-scout codebase operations

Read before changing code. Working method and locked decisions: `CLAUDE.md`.
Source of truth for spec/decisions: `PROJECT.md`.

> **State as of 2026-08-07:** scaffold only. The layout below is the agreed target, not yet
> built. The first implementation task creates `fetch.py` and its tests.

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
| Fetching | `src/pulse_scout/sources/` | Only place that touches the network. Behind a `FeedSource` seam. |
| Core logic | `src/pulse_scout/core/` | Pure. No network, no Ollama, no filesystem. Dedup, ranking, threading. |
| Model calls | `src/pulse_scout/llm/` | Only place that talks to Ollama. Behind a `Scorer` / `Writer` / `Embedder` seam. |
| Storage | `src/pulse_scout/store/` | SQLite. Schema migrations by `PRAGMA user_version`. |
| API | `src/pulse_scout/api.py` | FastAPI. Reads finished digests. **Computes nothing.** |
| Frontend | `frontend/` | React + Vite, built to static files, served by the API process. |
| CLIs | `scripts/` | Thin. Argument parsing plus a call into the pipeline. |

Config is `data/sources.toml`, read with the standard library `tomllib` — no dependency.

## Run / build / test

```bash
uv sync
uv run pytest -q          # gate part 1
uv run ruff check .       # gate part 2
uv run python scripts/fetch_once.py       # (planned) one fetch cycle into .cache/
uv run python scripts/build_digest.py     # (planned) full pipeline, writes today's digest
uv run uvicorn pulse_scout.api:app --port 8430   # (planned) the PWA
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
  sources log a warning and are skipped; anything else failing should be loud.
