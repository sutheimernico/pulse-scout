"""Tests for the throughput benchmark's pure parts. The live run is a script, not a test."""

from __future__ import annotations

import pytest

from pulse_scout.benchmark import (
    CallMeasurement,
    PassReport,
    daily_budget_seconds,
    score_pass,
    synthetic_text,
    write_pass,
)
from tests.fakes import FakeClient


def measurement(prompt_tokens: int = 100, **kwargs) -> CallMeasurement:
    defaults = {
        "prompt_tokens": prompt_tokens,
        "output_tokens": 10,
        "prompt_seconds": 1.0,
        "output_seconds": 2.0,
        "total_seconds": 3.0,
    }
    return CallMeasurement(**(defaults | kwargs))


def test_synthetic_text_hits_the_target_size_roughly() -> None:
    text = synthetic_text(200)
    estimated = len(text) / 4.2
    assert 180 <= estimated <= 230
    # Deterministic for a seed, so two benchmark runs are comparable.
    assert synthetic_text(50, seed=3) == synthetic_text(50, seed=3)
    assert synthetic_text(50, seed=3) != synthetic_text(50, seed=4)


def test_synthetic_text_of_zero_is_empty() -> None:
    assert synthetic_text(0) == ""


def test_throughput_aggregates_over_calls() -> None:
    report = PassReport("score", "m", [measurement(), measurement()])
    assert report.prompt_tokens_per_second == pytest.approx(100.0)
    assert report.output_tokens_per_second == pytest.approx(5.0)
    assert report.wall_seconds == pytest.approx(6.0)


def test_prefix_cache_ratio_is_measured_in_time_not_tokens() -> None:
    """Ollama reports the full prompt_eval_count whether or not the prefix was cached.

    Verified live on 2026-09-20: three calls sharing a 381-token system block all reported
    381 tokens, while the intake time fell from 8,43 s to 0,22 s. A token-based metric would
    have concluded "no cache" and sent the budget decision the wrong way.
    """
    cached = PassReport(
        "score",
        "m",
        [measurement(350, prompt_seconds=8.0)] + [measurement(350, prompt_seconds=0.8)] * 4,
    )
    assert cached.prefix_cache_ratio == pytest.approx(0.9)

    cold = PassReport("score", "m", [measurement(350, prompt_seconds=8.0)] * 5)
    assert cold.prefix_cache_ratio == pytest.approx(0.0)


def test_prefix_cache_ratio_is_unknown_below_three_calls() -> None:
    assert PassReport("score", "m", [measurement()]).prefix_cache_ratio is None
    assert PassReport("score", "m", []).prompt_tokens_per_second == 0.0


def test_score_pass_reuses_one_identical_system_block() -> None:
    """A per-call system block would defeat the prefix cache — and the 2-minute budget."""
    client = FakeClient(replies=["7"] * 5)
    report = score_pass(
        client, model="small", candidates=5, system_tokens=50, item_tokens=30, output_cap=8
    )

    systems = {call["system"] for call in client.calls}
    assert len(systems) == 1
    assert len(report.calls) == 5
    # Every prompt differs, or the benchmark would measure a cache hit that real items cannot get.
    assert len({call["prompt"] for call in client.calls}) == 5


def test_score_pass_marks_its_prompts_as_synthetic() -> None:
    client = FakeClient(replies=["7"])
    score_pass(client, model="small", candidates=1, system_tokens=20, item_tokens=10, output_cap=8)
    assert "SYNTHETIC" in client.calls[0]["system"]


def test_write_pass_sizes_the_context_window() -> None:
    client = FakeClient(replies=["digest"])
    write_pass(client, model="big", context_tokens=4000, output_cap=700)
    options = client.calls[0]["options"]
    assert options["num_predict"] == 700
    assert options["num_ctx"] >= 4700


def test_daily_budget_is_the_sum_of_both_passes() -> None:
    score = PassReport("score", "s", [measurement()] * 3)
    write = PassReport("write", "w", [measurement(total_seconds=400.0)])
    assert daily_budget_seconds(score, write) == pytest.approx(409.0)


def test_report_dict_is_json_shaped() -> None:
    report = PassReport(
        "score",
        "m",
        [measurement(350, prompt_seconds=8.0)] + [measurement(350, prompt_seconds=0.8)] * 2,
    )
    as_dict = report.as_dict()
    assert as_dict["calls"] == 3
    assert as_dict["model"] == "m"
    assert as_dict["prefix_cache_ratio"] == pytest.approx(0.9)
    # The verdict must stay checkable against the raw per-call numbers.
    assert as_dict["prompt_tokens_per_call"] == [350, 350, 350]
    assert as_dict["prompt_seconds_per_call"] == [8.0, 0.8, 0.8]
