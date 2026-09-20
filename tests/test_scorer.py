"""Tests for the scoring pass.

Two of these carry weight beyond themselves: the system block must stay byte-identical across
calls (or the prefix cache, and with it the two-minute budget, is gone), and an unparseable
answer must never turn into a guessed number.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pulse_scout.core.dedupe import Cluster
from pulse_scout.core.ranking import Candidate
from pulse_scout.llm.ollama import OllamaError
from pulse_scout.llm.scorer import (
    parse_score,
    score_candidates,
    spearman,
)
from pulse_scout.models import Item
from tests.fakes import FakeClient

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def candidate(title: str, score: float = 1.0) -> Candidate:
    item = Item.create(
        source_name="Feed",
        tier=1,
        title=title,
        url=f"https://example.test/{abs(hash(title)) % 10_000}",
        summary="A summary of the story.",
        published_at=NOW,
    )
    return Candidate(cluster=Cluster(members=(item,)), score=score)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("7\nrelevant to his backend", 7),
        ("10", 10),
        ("0\nmarketing", 0),
        ("  8  \n  a reason  ", 8),
        ("I would rate this a 6 out of 10.", 6),
        ("Sure! Here is my rating:\n7", 7),
    ],
)
def test_scores_are_recovered_from_chatty_answers(text: str, expected: int) -> None:
    value, _reason = parse_score(text)
    assert value == expected


@pytest.mark.parametrize("text", ["", "   ", "I cannot rate this.", "high relevance"])
def test_an_answer_without_a_number_yields_no_score(text: str) -> None:
    """A guessed number here would be a fabricated input to the digest."""
    assert parse_score(text)[0] is None


def test_out_of_range_numbers_are_not_matched() -> None:
    assert parse_score("42")[0] is None


def test_the_reason_is_kept_and_bounded() -> None:
    _value, reason = parse_score("7\n" + "x" * 400)
    assert len(reason) == 160


def test_every_call_shares_one_byte_identical_system_block() -> None:
    """Ollama's prefix cache can only reuse an identical prefix. This is the 2-minute budget."""
    client = FakeClient(replies=["7", "5", "3"])
    score_candidates([candidate("A"), candidate("B"), candidate("C")], client=client)

    systems = {call["system"] for call in client.calls}
    assert len(systems) == 1
    # And every per-item prompt differs, or there is nothing to score.
    assert len({call["prompt"] for call in client.calls}) == 3


def test_the_system_block_describes_the_corrected_reader() -> None:
    """Spec §4 still says 'a data/BI developer working in Azure'. D7 revoked that."""
    client = FakeClient(replies=["7"])
    score_candidates([candidate("A")], client=client)
    system = client.calls[0]["system"].lower()

    assert "fastapi" in system
    assert "react" in system
    assert "architecture" in system
    assert "junior" not in system
    assert "business intelligence" not in system
    # The excluded topics are named so the small model does not have to infer them.
    assert "dbt" in system


def test_a_parse_failure_keeps_the_deterministic_rank_and_is_counted() -> None:
    client = FakeClient(replies=["9", "no idea", "4"])
    result = score_candidates(
        [candidate("A"), candidate("B"), candidate("C")], client=client
    )

    assert result.parse_failures == 1
    unrated = result.scored[1]
    assert unrated.model_score is None
    assert unrated.model_rank is None
    assert unrated.combined_rank == 2.0


def test_a_failed_call_is_recorded_without_killing_the_run() -> None:
    client = FakeClient(fail_with=OllamaError("connection refused"))
    result = score_candidates([candidate("A"), candidate("B")], client=client)

    assert result.call_failures == 2
    assert all(entry.model_score is None for entry in result.scored)
    assert "connection refused" in result.scored[0].error


def test_model_ranks_follow_the_model_scores() -> None:
    client = FakeClient(replies=["3", "9", "6"])
    result = score_candidates(
        [candidate("A"), candidate("B"), candidate("C")], client=client
    )

    by_title = {entry.candidate.title: entry for entry in result.scored}
    assert by_title["B"].model_rank == 1
    assert by_title["C"].model_rank == 2
    assert by_title["A"].model_rank == 3


def test_ties_break_on_the_deterministic_rank() -> None:
    """A 1.5B model on a 0-10 scale ties constantly, so the tie-break is most of the order."""
    client = FakeClient(replies=["7", "7", "7"])
    result = score_candidates(
        [candidate("A"), candidate("B"), candidate("C")], client=client
    )
    assert [entry.model_rank for entry in result.scored] == [1, 2, 3]


def test_finalists_use_the_combined_rank() -> None:
    client = FakeClient(replies=["1", "10", "1", "1"])
    result = score_candidates(
        [candidate("A"), candidate("B"), candidate("C"), candidate("D")], client=client
    )
    finalists = result.finalists(2)
    # B was second by the deterministic ranking and first by the model: combined rank 1.5.
    assert finalists[0].candidate.title == "B"
    assert len(finalists) == 2


def test_the_rank_correlation_is_reported() -> None:
    """The measurement that will eventually say whether this pass is worth its runtime."""
    agreeing = score_candidates(
        [candidate("A"), candidate("B"), candidate("C"), candidate("D")],
        client=FakeClient(replies=["9", "7", "5", "3"]),
    )
    assert agreeing.rank_correlation == pytest.approx(1.0)

    opposed = score_candidates(
        [candidate("A"), candidate("B"), candidate("C"), candidate("D")],
        client=FakeClient(replies=["3", "5", "7", "9"]),
    )
    assert opposed.rank_correlation == pytest.approx(-1.0)


def test_spearman_edges() -> None:
    assert spearman([1.0, 2.0], [1.0, 2.0]) is None  # too few points to mean anything
    assert spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None  # no spread
    assert spearman([1.0, 2.0, 3.0], [1.0, 2.0]) is None  # mismatched lengths


def test_scoring_nothing_is_not_an_error() -> None:
    result = score_candidates([], client=FakeClient())
    assert result.scored == []
    assert result.rank_correlation is None
