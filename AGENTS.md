# AGENTS.md — pulse-scout codebase operations

Read before changing code. Working method and locked decisions: `CLAUDE.md`.
Source of truth for spec/decisions: `PROJECT.md`.

> **State as of 2026-09-27:** stage 1 is built and scheduled — fetch, cache, parse,
> seen-filter, cluster, rank, score, write, validate, **fact-check**, store, serve, PWA,
> timer. Every row in the table below exists. Open: T23 (five-day observation, Nico's) and
> stage 2 (T24/T25). Plan and backlog: `docs/superpowers/plans/2026-09-20-pulse-scout-v1.md`
> and `PLAN.md`. Operations: `docs/ops.md`.

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
| Core logic | `src/pulse_scout/core/` | Pure. No network, no Ollama, no filesystem. `canonical`, `dedupe`, `ranking`, `selection`, `validate`, `faithfulness`, `digest`, `observation`. |
| Model calls | `src/pulse_scout/llm/` | Only place that talks to Ollama. `ollama.py` is the seam; `scorer`, `writer`, `verifier`, `prompts` sit on top. |
| Storage | `src/pulse_scout/store/` | SQLite. Schema migrations by `PRAGMA user_version` (currently v2). |
| Orchestration | `src/pulse_scout/pipeline.py` | Fetch → seen-filter → cluster → rank, plus the funnel counters. |
| API | `src/pulse_scout/api.py` | FastAPI, reads finished digests, **computes nothing.** Fail-closed token gate on `/api/*`, no loopback exception (tailscale serve forwards from 127.0.0.1). |
| Frontend | `frontend/` | React 19 + Vite PWA, built to `frontend/dist`, served by the API process. `public/sw.js` is a hand-written module worker; its decisions live in `public/sw-strategy.js` and are vitest-tested. |
| Operations | `deploy/`, `scripts/daily.sh`, `scripts/install_systemd.sh` | systemd user units: evening timer (`Persistent=true`) and the always-on web server. `docs/ops.md`. |
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
uv run python scripts/serve.py                 # API + PWA on :8430 (loopback without a token)
uv run python scripts/eval_faithfulness.py     # the fact check against labelled sentences
uv run python scripts/observe.py               # the five-day observation table
(cd frontend && npm test && npm run build)     # frontend gate: vitest + tsc + vite build
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
- **Changing the fact check** → `VERIFY_SYSTEM` in `llm/prompts.py`, then
  `uv run python scripts/eval_faithfulness.py --write --tag vN` and compare with the recorded
  runs in `data/benchmarks/`. A prompt change that is not measured is not a change. The
  `model-heldout` labels were scored only after v2 was frozen — tuning against them spends the
  only untuned number. `qwen2.5:1.5b` is not a usable checker (2 of 37 caught).
- **Changing the frontend** → `npm run build` afterwards; the web unit serves `frontend/dist`
  directly (restart it only if `dist/` did not exist when it started).
