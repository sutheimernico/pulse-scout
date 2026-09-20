"""Tests for clustering.

The headline pairs below are the contract. A false merge deletes a story from the digest; a
missed merge only costs a ranking bonus. The tests are written with that asymmetry in mind.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pulse_scout.core.dedupe import (
    Cluster,
    cluster_items,
    jaccard,
    normalise_title,
)
from pulse_scout.models import Item
from tests.fakes import slug

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def item(title: str, *, source: str = "S", url: str | None = None, tier: int = 3, hours: int = 0,
         summary: str = "") -> Item:
    return Item.create(
        source_name=source,
        tier=tier,
        title=title,
        url=url or f"https://{source.lower()}.test/{slug(title)}",
        summary=summary,
        published_at=NOW - timedelta(hours=hours),
    )


SAME_STORY = [
    (
        "Anthropic releases Claude with a longer context window",
        "Anthropic releases Claude with longer context window",
    ),
    ("FastAPI 0.120 is out", "FastAPI 0.120 out"),
    ("Show HN: A tool for reading feeds", "A tool for reading feeds"),
    ("Postgres 19 adds asynchronous I/O", "Postgres 19 adds asynchronous I/O support"),
]

DIFFERENT_STORY = [
    ("FastAPI 0.120 released", "FastAPI 0.119 released"),
    ("Azure Container Apps adds GPU support", "Azure Functions adds Python 3.14 support"),
    ("React 19.2 released", "Vue 4.0 released"),
    ("Anthropic ships a new model", "OpenAI ships a new model"),
]


@pytest.mark.parametrize(("left", "right"), SAME_STORY)
def test_headlines_about_one_story_merge(left: str, right: str) -> None:
    clusters = cluster_items([item(left, source="A"), item(right, source="B")])
    assert len(clusters) == 1, f"{left!r} and {right!r} should be one story"
    assert clusters[0].size == 2


@pytest.mark.parametrize(("left", "right"), DIFFERENT_STORY)
def test_headlines_about_different_stories_stay_apart(left: str, right: str) -> None:
    clusters = cluster_items([item(left, source="A"), item(right, source="B")])
    assert len(clusters) == 2, f"{left!r} and {right!r} are not the same story"


def test_the_same_url_from_two_sources_is_one_story() -> None:
    """Hacker News links to an article that also arrived through its own feed."""
    url = "https://example.test/the-article"
    clusters = cluster_items(
        [
            item("Something happened", source="HN", url=url + "?utm_source=hn"),
            item("A completely different headline", source="Blog", url=url),
        ]
    )
    assert len(clusters) == 1
    assert "same url" in clusters[0].reasons[0]


def test_clusters_outside_the_time_window_are_not_merged() -> None:
    title = "Anthropic releases Claude with a longer context window"
    clusters = cluster_items(
        [item(title, source="A", hours=0), item(title + " today", source="B", hours=200)]
    )
    assert len(clusters) == 2


def test_clustering_is_order_independent() -> None:
    items = [
        item("Postgres 19 adds asynchronous I/O", source="A"),
        item("React 19.2 released", source="B"),
        item("Postgres 19 adds asynchronous I/O support", source="C"),
    ]
    forwards = cluster_items(items)
    backwards = cluster_items(list(reversed(items)))
    assert sorted(c.size for c in forwards) == sorted(c.size for c in backwards)
    assert {frozenset(i.key for i in c.members) for c in forwards} == {
        frozenset(i.key for i in c.members) for c in backwards
    }


def test_output_follows_input_order() -> None:
    items = [item("First story here"), item("Second story there"), item("Third story yonder")]
    clusters = cluster_items(items)
    assert [c.primary.title for c in clusters] == [i.title for i in items]


def test_the_primary_member_is_the_one_with_the_richest_summary() -> None:
    title = "Anthropic releases Claude with a longer context window"
    clusters = cluster_items(
        [
            item(title, source="Thin", summary=""),
            item(title + " today", source="Rich", summary="Several sentences of context here."),
        ]
    )
    assert clusters[0].primary.source_name == "Rich"


def test_a_cluster_reports_its_best_tier_and_its_sources() -> None:
    title = "Azure Container Apps adds GPU support"
    clusters = cluster_items(
        [item(title, source="Aggregator", tier=3), item(title + " now", source="Azure", tier=1)]
    )
    assert clusters[0].best_tier == 1
    assert set(clusters[0].source_names) == {"Aggregator", "Azure"}


def test_an_empty_input_yields_no_clusters() -> None:
    assert cluster_items([]) == []


def test_a_single_item_is_its_own_cluster() -> None:
    clusters = cluster_items([item("Alone")])
    assert clusters[0].size == 1
    assert clusters[0].reasons == ()


def test_normalise_title_drops_noise_but_keeps_version_numbers() -> None:
    tokens = normalise_title("Show HN: The new FastAPI 0.120 is out")
    assert "0.120" in tokens
    assert "fastapi" in tokens
    assert "the" not in tokens
    assert "hn" not in tokens


def test_a_single_digit_is_kept_because_it_discriminates() -> None:
    """'Story 1' and 'Story 2' are two stories; dropping short tokens merged them."""
    assert normalise_title("Story number 1") != normalise_title("Story number 2")
    assert cluster_items([item("Story number 1"), item("Story number 2")]) != []
    assert len(cluster_items([item("Story number 1"), item("Story number 2")])) == 2


def test_normalise_title_never_returns_nothing() -> None:
    """A headline made entirely of stopwords must still be comparable."""
    assert normalise_title("How is it") != frozenset()


def test_jaccard_edges() -> None:
    assert jaccard(frozenset(), frozenset({"a"})) == 0.0
    assert jaccard(frozenset({"a"}), frozenset({"b"})) == 0.0
    assert jaccard(frozenset({"a", "b"}), frozenset({"a", "b"})) == 1.0
    assert jaccard(frozenset({"a", "b"}), frozenset({"b", "c"})) == pytest.approx(1 / 3)


def test_cluster_key_is_the_primary_key() -> None:
    single = Cluster(members=(item("Only one"),))
    assert single.key == single.primary.key
