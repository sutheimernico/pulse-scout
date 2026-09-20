# ADR 0001 — The daily throughput budget

**Date:** 2026-09-20 · **Status:** accepted, with a re-measurement owed
**Context:** spec §2 and §4; plan task T1; finding F5 in `docs/superpowers/plans/2026-09-20-pulse-scout-v1.md`

## Context

The whole architecture is a consequence of one pair of numbers measured on 2026-08-07 with
`qwen2.5:7b`: **18,1 tokens/s intake and 4,5 tokens/s generation**, CPU only. From those, the
spec derives a daily budget of about eight minutes — roughly two for the scoring pass over 40
candidates with `qwen2.5:1.5b`, and six for the writing pass.

The two-minute scoring figure was never measured. It only holds if (a) the 1.5B model is
several times faster than the 7B model on this CPU and (b) Ollama's prefix cache keeps the
shared system block across 40 consecutive calls. The plan's finding F5 flagged both as
assumptions, and T1 exists to test them before anything is built on the number.

## What was measured

`scripts/bench_ollama.py`, synthetic prompts of the designed shapes, no feed content.
Full results in `data/benchmarks/2026-09-20-ollama-throughput.json`.

| | measured 2026-09-20 | spec's figure |
|---|---|---|
| Scoring pass, 40 calls (`qwen2.5:1.5b`) | 8.139 intake tokens, 320 output tokens, **1.613 s (26,9 min)** | ~2 min |
| — intake | 28,6 tokens/s | — |
| — generation | **0,25 tokens/s** | — |
| Writing pass, 1 call (`qwen2.5:7b`) | 2.062 intake tokens, 140 output tokens, **322 s (5,4 min)** | ~6 min |
| — intake | 12,0 tokens/s | 18,1 tokens/s |
| — generation | 1,09 tokens/s | 4,5 tokens/s |
| **Daily total** | **32,3 min** | ~8 min |

## The measurement is contaminated, and that is the first finding

Load average during the run was **between 38 and 57 on a 16-thread machine**, caused by other
agent sessions running concurrently on the same laptop (`pytest` suites in three other private
repos, a retrieval evaluation, a headless browser). Ollama was getting a fraction of the CPU.

So the numbers above are a lower bound on throughput, not a measurement of the machine. The
clearest evidence is the variance rather than the mean: four consecutive scoring calls with
near-identical prompts took 3,75 s, 8,44 s, 1,56 s and 7,62 s of intake time. A 5× spread
across identical work is contention, not a property of the model.

`scripts/bench_ollama.py` now records `load_average_start` and `load_average_end` with every
report, so this can never again be read as a clean number by mistake.

## The prefix cache does work — and the first metric for it was wrong

The benchmark initially reported a prefix-cache ratio of **0,0**, which would have meant every
scoring call re-reads the whole system block and the two-minute budget is unreachable by
construction. That conclusion was wrong, and the way it was wrong is worth recording.

`prompt_eval_count` reports the **full prompt length on every call, cached or not**. Measured
directly with three consecutive calls sharing a 381-token system block:

| call | `prompt_eval_count` | `prompt_eval_duration` |
|---|---|---|
| 1 | 381 | 8,43 s |
| 2 | 381 | 0,34 s |
| 3 | 381 | 0,22 s |

The cache is working — a 96 % saving — and the token counter simply cannot see it. A
token-based metric therefore reports "no cache" precisely when the cache is doing its job, and
would have sent the budget decision in exactly the wrong direction. The metric now measures
`prompt_eval_duration`, and `data/benchmarks/*.json` records the per-call seconds so the
verdict stays checkable rather than believed.

## Decision

1. **The eight-minute budget is unproven, not disproven.** Nothing in the funnel's sizing
   changes on the strength of a measurement taken at load 50.
2. **Re-measure on an idle machine before tuning anything.** `uv run python
   scripts/bench_ollama.py` with nothing else running. The report now carries the load average,
   so the re-run is self-documenting. This is the one open item from T1.
3. **Generation is the bottleneck, not intake.** In both passes the decode phase dominated:
   the scoring pass spent 285 s on intake and roughly 1.280 s producing 320 tokens. Whatever
   the idle numbers turn out to be, the lever that matters is **output tokens**, not context
   size. That inverts the spec's emphasis, which treats context length as the scarcer resource.
4. **If the idle re-measurement still lands far above eight minutes, the order of reduction is:**
   output cap (700 → 500) first, then finalists (12 → 8), then candidates entering the scorer
   (40 → 20), then batching the scoring pass into calls of ten items. Scoring candidate count
   is the cheapest lever because finding F8 already questions whether that pass earns its time.
5. **Do not add a fifth model.** `llama3.1:8b` is present on the machine and is not used.
   Three models already cycle through 15 GB of RAM per run.

## Consequences

- The pipeline ships with the spec's sizes (40 candidates, 12 finalists, 700 output tokens)
  because there is no sound measurement to justify changing them.
- `scripts/build_digest.py` takes `--output-cap` and `--skip-scoring`, so the two largest costs
  can be varied from the command line while the real numbers are being collected.
- Every run records its own timings, so after a week of real runs the budget question is
  answered by the digests themselves rather than by another synthetic benchmark.

## Needs Nico

Run the benchmark once on an otherwise idle machine. Everything in item 4 waits on that.
