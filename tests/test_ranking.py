"""Tests for the deterministic ranking.

Each factor is tested on its own: change one input, and the order must move in the stated
direction and only then. That is the point of an explicit formula — if ranking were a bundle
of heuristics, none of these tests could be written.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pulse_scout.config import Source
from pulse_scout.core.dedupe import Cluster
from pulse_scout.core.ranking import (
    Candidate,
    engagement_percentiles,
    rank,
    recency_factor,
)
from pulse_scout.models import Item
from pulse_scout.profile import load_profile
from tests.fakes import slug

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
PROFILE = load_profile()


def source(name: str, *, weight: float = 1.0, tier: int = 3) -> Source:
    return Source(
        name=name,
        tier=tier,
        weight=weight,
        url=f"https://{name}.test/feed",
        kind="rss",
        abstract=True,
    )


def item(
    title: str,
    *,
    src: str = "S",
    tier: int = 3,
    hours: int = 0,
    engagement: dict[str, float] | None = None,
    summary: str = "",
    dated: bool = True,
) -> Item:
    return Item.create(
        source_name=src,
        tier=tier,
        title=title,
        url=f"https://{src.lower()}.test/{slug(title)}",
        summary=summary,
        published_at=NOW - timedelta(hours=hours) if dated else None,
        engagement=engagement,
    )


def score_of(cluster: Cluster, sources: dict[str, Source]) -> Candidate:
    return rank([cluster], sources=sources, profile=PROFILE, now=NOW)[0]


def test_tier_one_outranks_tier_three_all_else_equal() -> None:
    sources = {"A": source("A", tier=1), "B": source("B", tier=3)}
    clusters = [
        Cluster(members=(item("Something happened", src="B", tier=3),)),
        Cluster(members=(item("Something else happened", src="A", tier=1),)),
    ]
    ranked = rank(clusters, sources=sources, profile=PROFILE, now=NOW)
    assert ranked[0].tier == 1


def test_a_heavier_source_outranks_a_lighter_one() -> None:
    sources = {"Heavy": source("Heavy", weight=2.0), "Light": source("Light", weight=0.5)}
    clusters = [
        Cluster(members=(item("A story", src="Light"),)),
        Cluster(members=(item("Another story", src="Heavy"),)),
    ]
    best = rank(clusters, sources=sources, profile=PROFILE, now=NOW)[0]
    assert best.cluster.primary.source_name == "Heavy"


def test_keywords_from_nicos_stack_lift_an_item() -> None:
    sources = {"S": source("S")}
    plain = score_of(Cluster(members=(item("Some company raised a round"),)), sources)
    relevant = score_of(
        Cluster(members=(item("FastAPI 0.120 changes Alembic migrations"),)), sources
    )
    assert relevant.score > plain.score
    assert relevant.factors["keywords"] > plain.factors["keywords"]


def test_an_excluded_topic_is_demoted() -> None:
    """dbt and Kubernetes still arrive through the aggregators, which have no topic filter."""
    sources = {"S": source("S")}
    neutral = score_of(Cluster(members=(item("A conference was announced"),)), sources)
    excluded = score_of(Cluster(members=(item("Kubernetes 1.40 improves scheduling"),)), sources)
    assert excluded.score < neutral.score
    assert excluded.factors["negatives"] < 1.0


def test_an_excluded_term_alongside_a_strong_one_is_not_demoted() -> None:
    """'How we replaced dbt with FastAPI' is about his stack, not about dbt."""
    sources = {"S": source("S")}
    mixed = score_of(
        Cluster(members=(item("How we replaced dbt with FastAPI and PostgreSQL"),)), sources
    )
    assert mixed.factors["negatives"] == 1.0


def test_fresher_items_outrank_older_ones() -> None:
    sources = {"S": source("S")}
    fresh = score_of(Cluster(members=(item("A story", hours=1),)), sources)
    stale = score_of(Cluster(members=(item("Another story", hours=48),)), sources)
    assert fresh.score > stale.score


def test_recency_decays_by_half_a_day_at_a_time() -> None:
    day_old = recency_factor(NOW - timedelta(hours=24), now=NOW, profile=PROFILE)
    assert day_old == pytest.approx(0.5)
    assert recency_factor(NOW, now=NOW, profile=PROFILE) == pytest.approx(1.0)
    # A week-old item is floored rather than annihilated.
    week_old = recency_factor(NOW - timedelta(days=7), now=NOW, profile=PROFILE)
    assert week_old == PROFILE.recency_floor


def test_an_undated_item_gets_less_than_a_fresh_one_and_more_than_the_floor() -> None:
    undated = recency_factor(None, now=NOW, profile=PROFILE)
    assert PROFILE.recency_floor < undated < 1.0


def test_a_future_timestamp_does_not_earn_a_bonus() -> None:
    """Finextra mixes event announcements with future dates into its news feed."""
    assert recency_factor(NOW + timedelta(days=30), now=NOW, profile=PROFILE) == 1.0


def test_cross_source_duplication_lifts_a_story() -> None:
    sources = {name: source(name) for name in ("A", "B", "C")}
    title = "One story told three times"
    single = score_of(Cluster(members=(item(title, src="A"),)), sources)
    triple = score_of(
        Cluster(
            members=(item(title, src="A"), item(title + " x", src="B"), item(title + " y", src="C"))
        ),
        sources,
    )
    assert triple.factors["duplicates"] > single.factors["duplicates"]


def test_the_duplication_bonus_stops_at_the_cap() -> None:
    """Fifteen aggregators echoing one story must not buy the top slot."""
    sources = {f"S{i}": source(f"S{i}") for i in range(20)}
    members = tuple(item(f"Echo {i}", src=f"S{i}") for i in range(20))
    capped = score_of(Cluster(members=members), sources)
    at_cap = score_of(Cluster(members=members[: PROFILE.duplicate_cap + 1]), sources)
    assert capped.factors["duplicates"] == at_cap.factors["duplicates"]


def test_engagement_is_normalised_within_a_source() -> None:
    """A HuggingFace like and a Hacker News point are not the same unit."""
    clusters = [
        Cluster(members=(item("hn low", src="HN", engagement={"points": 25}),)),
        Cluster(members=(item("hn high", src="HN", engagement={"points": 500}),)),
        Cluster(members=(item("hf low", src="HF", engagement={"likes": 3}),)),
        Cluster(members=(item("hf high", src="HF", engagement={"likes": 1400}),)),
    ]
    percentiles = engagement_percentiles(clusters)
    assert percentiles[("HN", clusters[1].primary.key)] == 1.0
    assert percentiles[("HN", clusters[0].primary.key)] == 0.0
    # The big HuggingFace number does not outrank the big HN number just for being bigger.
    assert percentiles[("HF", clusters[3].primary.key)] == 1.0


def test_a_source_with_no_numbers_is_neutral_not_penalised() -> None:
    sources = {"S": source("S")}
    silent = score_of(Cluster(members=(item("No numbers here"),)), sources)
    assert silent.factors["engagement"] == 1.0


def test_a_lone_measured_item_lands_mid_field() -> None:
    """Otherwise every low-volume source would hand its single item a perfect percentile."""
    clusters = [Cluster(members=(item("only one", src="HN", engagement={"points": 7}),))]
    percentiles = engagement_percentiles(clusters)
    assert percentiles[("HN", clusters[0].primary.key)] == 0.5


def test_ranking_is_stable_across_runs() -> None:
    sources = {"S": source("S")}
    clusters = [Cluster(members=(item(f"Story number {i}"),)) for i in range(10)]
    first = [c.cluster.key for c in rank(clusters, sources=sources, profile=PROFILE, now=NOW)]
    second = [
        c.cluster.key
        for c in rank(list(reversed(clusters)), sources=sources, profile=PROFILE, now=NOW)
    ]
    assert first == second


def test_the_limit_returns_the_best_candidates() -> None:
    sources = {"S": source("S")}
    clusters = [Cluster(members=(item(f"Story {i}", hours=i),)) for i in range(10)]
    top = rank(clusters, sources=sources, profile=PROFILE, now=NOW, limit=3)
    assert len(top) == 3
    assert top == sorted(top, key=lambda c: -c.score)


def test_a_candidate_can_explain_itself() -> None:
    sources = {"S": source("S")}
    candidate = score_of(Cluster(members=(item("FastAPI 0.120 released"),)), sources)
    explanation = candidate.explain()
    for factor in ("source", "tier", "engagement", "keywords", "recency", "duplicates"):
        assert factor in explanation
