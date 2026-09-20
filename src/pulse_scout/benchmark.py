"""Measuring what the local model actually costs on this machine.

The whole architecture is a consequence of one pair of numbers — 18,1 tokens/s intake and
4,5 tokens/s generation — and those were measured for `qwen2.5:7b` only. The scoring budget in
the spec (40 items in ~2 minutes with `qwen2.5:1.5b`) was extrapolated from them, which only
holds if the small model is several times faster *and* Ollama's prefix cache keeps the shared
system block between consecutive calls. Both are assumptions. This module measures them.

The prompts here are **synthetic**: filler assembled from a fixed word pool, not feed content.
That is deliberate twice over — third-party text must never be committed (C4), and a benchmark
should measure token counts rather than the mood of one particular news day.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from pulse_scout.llm.ollama import Client, Completion

# Filler vocabulary. Deliberately drawn from this project's own domain so the token/word ratio
# is in the same range as a real prompt, and unmistakably not a real headline.
_FILLER_WORDS = (
    "pipeline", "service", "boundary", "migration", "container", "registry", "deployment",
    "latency", "throughput", "schema", "index", "partition", "rollout", "observability",
    "tracing", "retention", "validation", "contract", "dependency", "interface", "adapter",
    "scheduler", "cache", "invalidation", "backpressure", "queue", "consumer", "release",
    "candidate", "regression", "benchmark", "allocation", "compaction", "checkpoint",
    "replica", "quorum",
)

# Rough English tokenisation ratio. Only used to *aim* at a size; every report also records the
# token count the model actually reported, so the estimate never has to be believed.
_CHARS_PER_TOKEN = 4.2


def synthetic_text(target_tokens: int, *, seed: int = 0) -> str:
    """Filler of roughly `target_tokens` tokens, deterministic for a given seed."""
    if target_tokens <= 0:
        return ""
    target_chars = int(target_tokens * _CHARS_PER_TOKEN)
    words: list[str] = []
    length = 0
    index = seed
    while length < target_chars:
        word = _FILLER_WORDS[index % len(_FILLER_WORDS)]
        words.append(word)
        length += len(word) + 1
        index += 1
    return " ".join(words)


@dataclass(frozen=True, slots=True)
class CallMeasurement:
    """One generation, reduced to what the budget cares about."""

    prompt_tokens: int
    output_tokens: int
    prompt_seconds: float
    output_seconds: float
    total_seconds: float

    @classmethod
    def of(cls, completion: Completion) -> CallMeasurement:
        return cls(
            prompt_tokens=completion.prompt_tokens,
            output_tokens=completion.output_tokens,
            prompt_seconds=completion.prompt_seconds,
            output_seconds=completion.output_seconds,
            total_seconds=completion.total_seconds,
        )


@dataclass(frozen=True, slots=True)
class PassReport:
    """Aggregated throughput for one benchmark pass."""

    label: str
    model: str
    calls: list[CallMeasurement] = field(default_factory=list)

    @property
    def wall_seconds(self) -> float:
        return sum(call.total_seconds for call in self.calls)

    @property
    def prompt_tokens_per_second(self) -> float:
        tokens = sum(call.prompt_tokens for call in self.calls)
        seconds = sum(call.prompt_seconds for call in self.calls)
        return tokens / seconds if seconds > 0 else 0.0

    @property
    def output_tokens_per_second(self) -> float:
        tokens = sum(call.output_tokens for call in self.calls)
        seconds = sum(call.output_seconds for call in self.calls)
        return tokens / seconds if seconds > 0 else 0.0

    @property
    def prefix_cache_ratio(self) -> float | None:
        """How much of the shared prefix later calls skipped, 0,0 (none) to 1,0 (all).

        Ollama only counts the tokens it actually evaluated, so a working prefix cache shows up
        as a sharp drop in `prompt_eval_count` from the first call to the rest. Needs at least
        three calls to mean anything.
        """
        if len(self.calls) < 3:
            return None
        first = self.calls[0].prompt_tokens
        if first <= 0:
            return None
        later = statistics.median(call.prompt_tokens for call in self.calls[1:])
        return max(0.0, min(1.0, 1.0 - later / first))

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "model": self.model,
            "calls": len(self.calls),
            "wall_seconds": round(self.wall_seconds, 2),
            "prompt_tokens_total": sum(call.prompt_tokens for call in self.calls),
            "output_tokens_total": sum(call.output_tokens for call in self.calls),
            "prompt_tokens_per_second": round(self.prompt_tokens_per_second, 2),
            "output_tokens_per_second": round(self.output_tokens_per_second, 2),
            "prefix_cache_ratio": (
                None if self.prefix_cache_ratio is None else round(self.prefix_cache_ratio, 3)
            ),
            # Per-call intake, so the cache verdict above can be checked rather than believed.
            "prompt_tokens_per_call": [call.prompt_tokens for call in self.calls],
        }


def score_pass(
    client: Client,
    *,
    model: str,
    candidates: int,
    system_tokens: int,
    item_tokens: int,
    output_cap: int,
) -> PassReport:
    """The scoring stage: one short call per candidate, identical system block every time.

    The system block must be byte-identical across calls or the prefix cache cannot help, so
    it is built once, outside the loop. That is not a micro-optimisation here — it is the
    difference between two minutes and thirteen.
    """
    system = "SYNTHETIC BENCHMARK PROMPT — not real content.\n" + synthetic_text(system_tokens)
    report = PassReport(label="score", model=model)
    for index in range(candidates):
        prompt = synthetic_text(item_tokens, seed=index * 7)
        completion = client.generate(
            model=model,
            prompt=prompt,
            system=system,
            options={"num_predict": output_cap, "temperature": 0.0},
        )
        report.calls.append(CallMeasurement.of(completion))
    return report


def write_pass(
    client: Client, *, model: str, context_tokens: int, output_cap: int
) -> PassReport:
    """The writing stage: one long call, the shape of the real digest prompt."""
    prompt = "SYNTHETIC BENCHMARK PROMPT — not real content.\n" + synthetic_text(context_tokens)
    completion = client.generate(
        model=model,
        prompt=prompt,
        options={
            "num_predict": output_cap,
            "temperature": 0.0,
            "num_ctx": max(4096, context_tokens + output_cap + 512),
        },
    )
    return PassReport(label="write", model=model, calls=[CallMeasurement.of(completion)])


def daily_budget_seconds(score: PassReport, write: PassReport) -> float:
    """What one real run would cost, given these measurements."""
    return score.wall_seconds + write.wall_seconds
