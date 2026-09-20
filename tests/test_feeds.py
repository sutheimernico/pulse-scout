"""Tests for RSS and Atom parsing.

All fixtures are hand-written and synthetic — see `tests/fixtures/README.md`. No captured
third-party body is committed anywhere in this repository.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pulse_scout.sources.feeds import (
    FeedError,
    clean_text,
    parse_feed,
    parse_timestamp,
    sniff,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def parse(name: str, tier: int = 1):
    return parse_feed(fixture(name), source_name="Example", tier=tier)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("rss_minimal.xml", "xml"),
        ("atom_minimal.xml", "xml"),
        ("rss_with_bom.xml", "xml"),
        ("html_error_page.html", "html"),
    ],
)
def test_sniffing_reads_the_body_not_the_header(name: str, expected: str) -> None:
    assert sniff(fixture(name)) == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"", "unknown"),
        (b"   ", "unknown"),
        (b'{"a": 1}', "json"),
        (b"[1, 2]", "json"),
        (b"<!-- a comment -->\n<rss></rss>", "xml"),
        (b"plain text", "unknown"),
    ],
)
def test_sniffing_edge_cases(body: bytes, expected: str) -> None:
    assert sniff(body) == expected


def test_rss_is_parsed_with_urls_canonicalised() -> None:
    items = parse("rss_minimal.xml")
    assert [item.title for item in items] == [
        "Example Framework 9.9 released",
        "Example Framework 9.8 released",
    ]
    first = items[0]
    assert first.url == "https://example.test/posts/9-9"
    assert first.summary == "A synthetic release note."
    assert first.published_at == datetime(2026, 9, 19, 8, 30, tzinfo=UTC)
    assert first.raw_id == "example-9-9"
    assert first.tier == 1


def test_rss_timestamps_are_normalised_to_utc() -> None:
    second = parse("rss_minimal.xml")[1]
    assert second.published_at == datetime(2026, 9, 18, 7, 30, tzinfo=UTC)


def test_atom_uses_the_alternate_link_not_the_self_link() -> None:
    items = parse("atom_minimal.xml", tier=2)
    assert items[0].url == "https://example.test/releases/v2.0.0"
    assert items[0].summary == "Synthetic changelog."
    assert items[0].published_at == datetime(2026, 9, 19, 10, 0, tzinfo=UTC)
    assert items[1].published_at == datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def test_a_byte_order_mark_does_not_break_the_parse() -> None:
    """The Azure release feed sends one, and it is one of the highest-value tier 1 sources."""
    items = parse("rss_with_bom.xml")
    assert len(items) == 1
    assert items[0].title == "Synthetic service update"


def test_an_html_page_is_a_clear_error_not_an_empty_list() -> None:
    with pytest.raises(FeedError, match="HTML page"):
        parse("html_error_page.html")


def test_malformed_xml_is_an_error() -> None:
    with pytest.raises(FeedError, match="malformed XML"):
        parse("rss_broken.xml")


def test_json_in_a_feed_slot_names_the_likely_misconfiguration() -> None:
    with pytest.raises(FeedError, match="wrong kind"):
        parse_feed(b'[{"title": "x"}]', source_name="Lobsters", tier=3)


def test_an_unexpected_root_element_is_an_error() -> None:
    with pytest.raises(FeedError, match="unexpected root"):
        parse_feed(b"<?xml version='1.0'?><opml><body/></opml>", source_name="x", tier=1)


def test_undated_items_keep_a_null_date_and_untitled_ones_are_skipped() -> None:
    items = parse("rss_undated.xml")
    # Two of three entries survive; the one without a title cannot be ranked or shown.
    assert [item.title for item in items] == ["No date at all", "Unparseable date"]
    # None rather than now(): an undated item has not earned the recency bonus.
    assert all(item.published_at is None for item in items)


def test_rss_1_0_items_live_beside_the_channel() -> None:
    body = (
        b"<?xml version='1.0'?>"
        b"<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#' "
        b"xmlns='http://purl.org/rss/1.0/'>"
        b"<channel><title>c</title></channel>"
        b"<item><title>An RSS 1.0 item</title><link>https://example.test/x</link></item>"
        b"</rdf:RDF>"
    )
    items = parse_feed(body, source_name="Example", tier=3)
    assert [item.title for item in items] == ["An RSS 1.0 item"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sat, 19 Sep 2026 08:30:00 +0000", datetime(2026, 9, 19, 8, 30, tzinfo=UTC)),
        ("2026-09-19T10:00:00Z", datetime(2026, 9, 19, 10, 0, tzinfo=UTC)),
        ("2026-09-19T12:00:00+02:00", datetime(2026, 9, 19, 10, 0, tzinfo=UTC)),
        ("2026-09-19", datetime(2026, 9, 19, 0, 0, tzinfo=UTC)),
        ("letzten Dienstag", None),
        ("", None),
        (None, None),
    ],
)
def test_timestamp_parsing(raw: str | None, expected: datetime | None) -> None:
    assert parse_timestamp(raw) == expected


def test_clean_text_strips_markup_and_truncates() -> None:
    assert clean_text("<p>Hello &amp; <b>welcome</b></p>") == "Hello & welcome"
    assert clean_text(None) == ""
    long = clean_text("word " * 400)
    assert len(long) <= 801
    assert long.endswith("…")
