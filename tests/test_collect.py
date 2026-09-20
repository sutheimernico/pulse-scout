"""Tests for the collector — in particular its failure policy."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pulse_scout.config import Source
from pulse_scout.sources.cache import RawCache
from pulse_scout.sources.collect import (
    MAX_FAILURE_RATIO,
    CollectError,
    collect,
    resolve_url,
)
from pulse_scout.sources.http import FetchResult

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

RSS = (
    b"<?xml version='1.0'?><rss version='2.0'><channel>"
    b"<item><title>A synthetic item</title><link>https://example.test/a</link></item>"
    b"</channel></rss>"
)


def source(name: str, *, kind: str = "rss", fragile: bool = False, url: str | None = None):
    return Source(
        name=name,
        tier=1,
        weight=1.0,
        url=url or f"https://example.test/{name}.xml",
        kind=kind,
        abstract=True,
        fragile=fragile,
    )


class StubFetcher:
    """Answers per URL. Anything not in the map is a connection failure."""

    def __init__(self, responses: dict[str, FetchResult]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, str | None]] = []

    def fetch(self, url, *, etag=None, last_modified=None):
        self.requests.append((url, etag))
        return self.responses.get(
            url, FetchResult(url=url, error="ConnectionRefusedError: refused")
        )


def ok(url: str, body: bytes = RSS, **kwargs) -> FetchResult:
    return FetchResult(url=url, status=200, body=body, **kwargs)


def test_a_clean_run_collects_every_item() -> None:
    sources = [source("a"), source("b")]
    fetcher = StubFetcher({s.url: ok(s.url) for s in sources})

    report = collect(sources, fetcher=fetcher, now=NOW)

    assert len(report.items) == 2
    assert report.failed == []
    assert all(outcome.item_count == 1 for outcome in report.outcomes)


def test_a_304_counts_as_success_with_no_items() -> None:
    src = source("a")
    fetcher = StubFetcher({src.url: FetchResult(url=src.url, status=304)})

    report = collect([src], fetcher=fetcher, now=NOW, validators={"a": ('"v1"', None)})

    assert report.items == []
    assert report.outcomes[0].ok is True
    assert report.outcomes[0].unchanged is True
    assert fetcher.requests[0][1] == '"v1"'
    # The validator survives a 304, or the next run would re-download everything.
    assert report.outcomes[0].etag == '"v1"'


def test_a_fragile_source_going_down_is_skipped_not_failed() -> None:
    """All three nitter mirrors were dead on 2026-09-20. That must not fail the run."""
    sources = [source("live"), source("nitter", fragile=True)]
    fetcher = StubFetcher({sources[0].url: ok(sources[0].url)})

    report = collect(sources, fetcher=fetcher, now=NOW)

    assert len(report.items) == 1
    assert [o.source_name for o in report.skipped] == ["nitter"]
    assert report.failed == []


def test_one_hard_failure_is_recorded_but_the_run_continues() -> None:
    sources = [source(name) for name in "abcd"]
    fetcher = StubFetcher({s.url: ok(s.url) for s in sources[:3]})

    report = collect(sources, fetcher=fetcher, now=NOW)

    assert len(report.items) == 3
    assert [o.source_name for o in report.failed] == ["d"]


def test_mass_failure_aborts_the_whole_run() -> None:
    """A confident digest built on a third of the sources is the failure this rule prevents."""
    sources = [source(name) for name in "abcd"]
    fetcher = StubFetcher({sources[0].url: ok(sources[0].url)})

    with pytest.raises(CollectError, match="Refusing to build a digest"):
        collect(sources, fetcher=fetcher, now=NOW)


def test_the_abort_threshold_is_a_ratio_of_non_fragile_sources() -> None:
    # 2 of 8 non-fragile down = 25 %, under the threshold; the fragile ones do not count.
    sources = [source(str(i)) for i in range(8)] + [source("x", fragile=True)]
    fetcher = StubFetcher({s.url: ok(s.url) for s in sources[:6]})

    report = collect(sources, fetcher=fetcher, now=NOW)

    assert len(report.failed) / 8 <= MAX_FAILURE_RATIO
    assert len(report.items) == 6


def test_an_unparseable_body_fails_that_source_only() -> None:
    sources = [source("html"), source("good")]
    fetcher = StubFetcher(
        {
            sources[0].url: ok(sources[0].url, b"<!DOCTYPE html><html>nope</html>"),
            sources[1].url: ok(sources[1].url),
        }
    )

    # The abort threshold is relaxed here so the per-source behaviour is what is under test.
    report = collect(sources, fetcher=fetcher, now=NOW, max_failure_ratio=0.6)

    assert [o.source_name for o in report.failed] == ["html"]
    assert "FeedError" in report.failed[0].error
    assert len(report.items) == 1


def test_raw_bodies_go_to_the_cache_not_into_the_report(tmp_path) -> None:
    src = source("a")
    fetcher = StubFetcher({src.url: ok(src.url)})
    cache = RawCache(tmp_path)

    collect([src], fetcher=fetcher, cache=cache, now=NOW)

    assert (tmp_path / "2026-09-20" / "a.xml").read_bytes() == RSS


def test_the_since_placeholder_becomes_a_unix_timestamp() -> None:
    url = "https://hn.algolia.com/api/v1/search?numericFilters=created_at_i%3E{since}"
    resolved = resolve_url(url, now=NOW, window_hours=24)
    assert "{since}" not in resolved
    assert resolved.endswith(str(int(NOW.timestamp()) - 24 * 3600))


def test_urls_without_a_placeholder_are_untouched() -> None:
    assert resolve_url("https://example.test/f", now=NOW, window_hours=24) == (
        "https://example.test/f"
    )


def test_the_placeholder_is_expanded_before_fetching() -> None:
    src = source("hn", url="https://example.test/s?since={since}")
    fetcher = StubFetcher({})
    collect([src], fetcher=fetcher, now=NOW, window_hours=24, max_failure_ratio=1.0)
    assert "{since}" not in fetcher.requests[0][0]


def test_the_summary_line_reports_real_numbers() -> None:
    sources = [source("a"), source("b"), source("c", fragile=True)]
    fetcher = StubFetcher({sources[0].url: ok(sources[0].url)})

    report = collect(sources, fetcher=fetcher, now=NOW, max_failure_ratio=0.6)

    assert report.summary_line() == "1 items from 2/3 sources (0 unchanged, 1 skipped, 1 failed)"


ARCHIVE_RSS = (
    b"<?xml version='1.0'?><rss version='2.0'><channel>"
    b"<item><title>From yesterday</title><link>https://example.test/new</link>"
    b"<pubDate>Sat, 19 Sep 2026 12:00:00 +0000</pubDate></item>"
    b"<item><title>From 2008</title><link>https://example.test/ancient</link>"
    b"<pubDate>Tue, 24 Jun 2008 12:00:00 +0000</pubDate></item>"
    b"<item><title>Undated release</title><link>https://example.test/rel</link></item>"
    b"</channel></rss>"
)


def test_archive_feeds_are_cut_to_the_window() -> None:
    """ThoughtWorks Insights returns 2.722 entries going back to 2008. All of them, every day."""
    src = source("archive")
    fetcher = StubFetcher({src.url: ok(src.url, ARCHIVE_RSS)})

    report = collect([src], fetcher=fetcher, now=NOW, window_hours=72)

    assert [item.title for item in report.items] == ["From yesterday", "Undated release"]
    assert report.outcomes[0].item_count == 2
