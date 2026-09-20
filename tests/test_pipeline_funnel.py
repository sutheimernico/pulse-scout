"""End-to-end test of the deterministic funnel, with a fake fetcher and a temporary database.

The second run in `test_a_second_run_over_the_same_feeds_finds_nothing_new` is the whole point
of the design: the sources are snapshots, so without the seen-set every morning would start
from scratch.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pulse_scout.config import Source
from pulse_scout.pipeline import run_funnel
from pulse_scout.profile import load_profile
from pulse_scout.sources.http import FetchResult
from pulse_scout.store.db import connect

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
PROFILE = load_profile()


def feed(*entries: tuple[str, str]) -> bytes:
    items = "".join(
        f"<item><title>{title}</title><link>{url}</link>"
        f"<pubDate>Sat, 20 Sep 2026 10:00:00 +0000</pubDate></item>"
        for title, url in entries
    )
    return (
        f"<?xml version='1.0'?><rss version='2.0'><channel>{items}</channel></rss>"
    ).encode()


class StubFetcher:
    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies
        self.validators_seen: list[str | None] = []

    def fetch(self, url, *, etag=None, last_modified=None):
        self.validators_seen.append(etag)
        body = self.bodies.get(url)
        if body is None:
            return FetchResult(url=url, error="ConnectionRefusedError")
        return FetchResult(url=url, status=200, body=body, headers={"etag": '"v1"'})


def source(name: str, *, tier: int = 1, weight: float = 1.0) -> Source:
    return Source(
        name=name,
        tier=tier,
        weight=weight,
        url=f"https://{name}.test/feed.xml",
        kind="rss",
        abstract=True,
    )


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "pulse.db")
    yield connection
    connection.close()


def run(db, sources, fetcher, *, now=NOW, **kwargs):
    return run_funnel(
        connection=db,
        sources=sources,
        profile=PROFILE,
        fetcher=fetcher,
        now=now,
        **kwargs,
    )


def test_the_funnel_counts_what_it_actually_did(db) -> None:
    sources = [source("azure", tier=1), source("noise", tier=3)]
    fetcher = StubFetcher(
        {
            sources[0].url: feed(
                ("Azure Container Apps adds GPU support", "https://a.test/1"),
                ("FastAPI 0.120 released", "https://a.test/2"),
            ),
            sources[1].url: feed(("A crypto company raised a round", "https://b.test/1")),
        }
    )

    result = run(db, sources, fetcher)

    assert result.counters.items_seen == 3
    assert result.counters.items_new == 3
    assert result.counters.clusters == 3
    assert result.counters.candidates == 3
    assert result.counters.sources_ok == 2
    assert result.counters.sources_failed == 0


def test_a_second_run_over_the_same_feeds_finds_nothing_new(db) -> None:
    sources = [source("azure")]
    fetcher = StubFetcher({sources[0].url: feed(("A story", "https://a.test/1"))})

    first = run(db, sources, fetcher)
    second = run(db, sources, fetcher, now=NOW + timedelta(days=1))

    assert first.counters.items_new == 1
    assert second.counters.items_seen == 1
    assert second.counters.items_new == 0
    assert second.counters.candidates == 0


def test_the_stored_validator_is_sent_on_the_next_run(db) -> None:
    sources = [source("azure")]
    fetcher = StubFetcher({sources[0].url: feed(("A story", "https://a.test/1"))})

    run(db, sources, fetcher)
    run(db, sources, fetcher, now=NOW + timedelta(days=1))

    assert fetcher.validators_seen == [None, '"v1"']


def test_relevant_items_outrank_noise(db) -> None:
    sources = [source("mixed", tier=1)]
    fetcher = StubFetcher(
        {
            sources[0].url: feed(
                ("Someone opened a coffee shop", "https://a.test/1"),
                ("FastAPI and Alembic change how migrations run", "https://a.test/2"),
            )
        }
    )

    result = run(db, sources, fetcher)

    assert result.candidates[0].title.startswith("FastAPI")


def test_the_candidate_limit_is_respected(db) -> None:
    sources = [source("many")]
    entries = tuple((f"Story number {i}", f"https://a.test/{i}") for i in range(20))
    fetcher = StubFetcher({sources[0].url: feed(*entries)})

    result = run(db, sources, fetcher, candidate_limit=5)

    assert result.counters.items_new == 20
    assert result.counters.candidates == 5


def test_the_headline_shows_real_numbers(db) -> None:
    sources = [source("a")]
    fetcher = StubFetcher({sources[0].url: feed(("A story", "https://a.test/1"))})

    result = run(db, sources, fetcher)

    assert result.counters.headline() == "1 gesichtet → 1 Kandidaten"


def test_the_run_row_records_the_same_counters(db) -> None:
    sources = [source("a")]
    fetcher = StubFetcher({sources[0].url: feed(("A story", "https://a.test/1"))})

    result = run(db, sources, fetcher)

    row = db.execute("SELECT * FROM runs WHERE id = ?", (result.run_id,)).fetchone()
    assert row["items_seen"] == 1
    assert row["items_new"] == 1
    assert row["finished_at"] is not None
    assert "1 items from 1/1 sources" in row["notes"]


def test_one_story_from_two_sources_becomes_one_candidate(db) -> None:
    sources = [source("blog", tier=1), source("aggregator", tier=3)]
    title = "Anthropic releases Claude with a longer context window"
    fetcher = StubFetcher(
        {
            sources[0].url: feed((title, "https://blog.test/claude")),
            sources[1].url: feed((title + " today", "https://agg.test/claude")),
        }
    )

    result = run(db, sources, fetcher)

    assert result.counters.items_new == 2
    assert result.counters.candidates == 1
    # The cross-source bonus is what makes duplication an importance signal.
    assert result.candidates[0].factors["duplicates"] > 1.0
    # And the better tier wins, so the story is credited to his own field.
    assert result.candidates[0].tier == 1
