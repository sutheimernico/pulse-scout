#!/usr/bin/env python3
"""Measure this machine's Ollama throughput for the two prompt shapes the pipeline uses.

Writes a JSON report to `data/benchmarks/`. Talks to a real, running Ollama — it is a
measurement tool, not part of the test suite.

    uv run python scripts/bench_ollama.py             # full run, ~10-15 minutes of CPU
    uv run python scripts/bench_ollama.py --quick     # shape check, ~1 minute
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulse_scout.benchmark import (  # noqa: E402
    daily_budget_seconds,
    score_pass,
    write_pass,
)
from pulse_scout.llm.ollama import OllamaClient  # noqa: E402

SCORE_MODEL = "qwen2.5:1.5b"
WRITE_MODEL = "qwen2.5:7b"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="4 scoring calls, short write")
    parser.add_argument("--candidates", type=int, default=40)
    parser.add_argument("--context-tokens", type=int, default=4000)
    parser.add_argument("--output-cap", type=int, default=700)
    args = parser.parse_args()

    candidates = 4 if args.quick else args.candidates
    context_tokens = 600 if args.quick else args.context_tokens
    output_cap = 40 if args.quick else args.output_cap

    client = OllamaClient()

    print(f"scoring pass: {candidates} calls against {SCORE_MODEL} ...", flush=True)
    score = score_pass(
        client,
        model=SCORE_MODEL,
        candidates=candidates,
        system_tokens=200,
        item_tokens=150,
        output_cap=8,
    )
    print(
        f"  {score.prompt_tokens_per_second:.1f} tok/s in, "
        f"{score.output_tokens_per_second:.1f} tok/s out, "
        f"{score.wall_seconds:.0f}s total, cache ratio {score.prefix_cache_ratio}",
        flush=True,
    )

    print(f"writing pass: {context_tokens} tokens into {WRITE_MODEL} ...", flush=True)
    write = write_pass(
        client, model=WRITE_MODEL, context_tokens=context_tokens, output_cap=output_cap
    )
    print(
        f"  {write.prompt_tokens_per_second:.1f} tok/s in, "
        f"{write.output_tokens_per_second:.1f} tok/s out, "
        f"{write.wall_seconds:.0f}s total",
        flush=True,
    )

    budget = daily_budget_seconds(score, write)
    report = {
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "note": "Synthetic prompts (filler words, no feed content). Sizes match the design.",
        "quick": args.quick,
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor() or "unknown",
        },
        "score": score.as_dict(),
        "write": write.as_dict(),
        "daily_budget_seconds": round(budget, 1),
        "daily_budget_minutes": round(budget / 60, 1),
    }

    out_dir = ROOT / "data" / "benchmarks"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    suffix = "-quick" if args.quick else ""
    path = out_dir / f"{stamp}-ollama-throughput{suffix}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"\ndaily budget: {budget / 60:.1f} min  ->  {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
