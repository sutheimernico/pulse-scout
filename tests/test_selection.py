"""Tests for selection.

The per-tier cap (D8) and the quiet-day behaviour (D-P8) are the two rules worth breaking the
build over, so both get explicit cases.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pulse_scout.core.dedupe import Cluster
from pulse_scout.core.ranking import Candidate
from pulse_scout.core.selection import (
    KUER_PER_GROUP,
    KUER_SLOTS,
    PFLICHT_SLOTS,
    select,
)
from pulse_scout.llm.scorer import ScoredCandidate
from pulse_scout.models import Item
from tests.fakes import slug

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def entry(title: str, *, tier: int = 1, rank: int = 1, model_score: int | None = 8):
    item = Item.create(
        source_name="Feed",
        tier=tier,
        title=title,
        url=f"https://example.test/{slug(title)}",
        published_at=NOW,
    )
    return ScoredCandidate(
        candidate=Candidate(cluster=Cluster(members=(item,)), score=1.0),
        deterministic_rank=rank,
        model_score=model_score,
        model_rank=rank,
    )


def test_five_slots_are_filled_when_five_qualify() -> None:
    finalists = [entry(f"Story {i}", tier=1 + i % 3, rank=i) for i in range(1, 9)]
    selection = select(finalists)
    assert len(selection.pflicht) == PFLICHT_SLOTS
    assert selection.is_quiet_day is False


def test_one_tier_cannot_take_more_than_three_slots() -> None:
    """D8: otherwise a busy AI news day pushes his own job out of his own digest."""
    finalists = [entry(f"AI story {i}", tier=2, rank=i) for i in range(1, 6)]
    finalists += [entry("A backend story", tier=1, rank=6), entry("A broad story", tier=3, rank=7)]

    selection = select(finalists)

    tiers = [e.candidate.tier for e in selection.pflicht]
    assert tiers.count(2) == 3
    assert set(tiers) == {1, 2, 3}
    assert selection.tier_capped == 2


def test_items_pushed_out_by_the_cap_land_in_the_kuer() -> None:
    finalists = [entry(f"AI story {i}", tier=2, rank=i) for i in range(1, 6)]
    selection = select(finalists)
    assert len(selection.pflicht) == 3
    assert len(selection.kuer) == 2


def test_a_quiet_day_shows_fewer_than_five() -> None:
    """Filling a slot to reach five would be fabrication with extra steps."""
    finalists = [
        entry("A good story", tier=1, rank=1, model_score=9),
        entry("Another good story", tier=2, rank=2, model_score=7),
        entry("Filler", tier=3, rank=3, model_score=1),
        entry("More filler", tier=3, rank=4, model_score=0),
    ]
    selection = select(finalists)

    assert len(selection.pflicht) == 2
    assert selection.is_quiet_day is True
    assert selection.below_threshold == 2
    assert selection.qualified == 2


def test_an_unrated_item_is_not_punished_for_our_parse_failure() -> None:
    finalists = [entry("Unrated", tier=1, rank=1, model_score=None)]
    selection = select(finalists)
    assert len(selection.pflicht) == 1


def test_the_kuer_is_capped_in_total() -> None:
    rest = [entry(f"Line {i}", tier=1 + i % 3, rank=i, model_score=5) for i in range(1, 40)]
    selection = select([], rest)
    assert len(selection.kuer) == KUER_SLOTS


def test_the_kuer_is_capped_per_group() -> None:
    rest = [entry(f"AI line {i}", tier=2, rank=i) for i in range(1, 30)]
    selection = select([], rest)
    assert len(selection.kuer) == KUER_PER_GROUP


def test_kuer_groups_come_back_in_tier_order() -> None:
    rest = [
        entry("Broad", tier=3, rank=1),
        entry("Stack", tier=1, rank=2),
        entry("Models", tier=2, rank=3),
    ]
    groups = select([], rest).kuer_groups()
    assert list(groups) == [1, 2, 3]


def test_a_pflicht_item_never_appears_again_in_the_kuer() -> None:
    finalists = [entry(f"Story {i}", tier=1 + i % 3, rank=i) for i in range(1, 9)]
    selection = select(finalists)

    pflicht_keys = {e.candidate.cluster.key for e in selection.pflicht}
    kuer_keys = {e.candidate.cluster.key for e in selection.kuer}
    assert pflicht_keys & kuer_keys == set()


def test_nothing_at_all_is_an_empty_selection_not_a_crash() -> None:
    selection = select([], [])
    assert selection.pflicht == []
    assert selection.kuer == []
    assert selection.is_quiet_day is True
