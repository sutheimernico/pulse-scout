"""Tests for URL canonicalisation and item identity.

The table below is the contract. Getting it wrong in one direction re-ingests the same story
every day; getting it wrong in the other silently deletes a story from the digest.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pulse_scout.core.canonical import canonical_url, item_key
from pulse_scout.models import Item

SAME = [
    # (a, b, why)
    (
        "https://example.com/post?utm_source=rss&utm_medium=feed",
        "https://example.com/post",
        "tracking parameters identify the referrer, not the content",
    ),
    ("https://example.com/post/", "https://example.com/post", "trailing slash"),
    ("https://EXAMPLE.com/Post", "https://example.com/Post", "host case, but not path case"),
    ("https://www.example.com/post", "https://example.com/post", "www"),
    ("https://m.example.com/post", "https://example.com/post", "mobile host"),
    ("https://amp.example.com/post", "https://example.com/post", "amp host"),
    ("https://example.com/post/amp", "https://example.com/post", "amp path"),
    ("https://example.com/post#section", "https://example.com/post", "fragment"),
    ("https://example.com:443/post", "https://example.com/post", "default port"),
    ("https://example.com/p?b=2&a=1", "https://example.com/p?a=1&b=2", "parameter order"),
    ("https://example.com/post?fbclid=xyz", "https://example.com/post", "facebook click id"),
    ("  https://example.com/post ", "https://example.com/post", "surrounding whitespace"),
]

DIFFERENT = [
    ("https://example.com/a", "https://example.com/b", "different path"),
    ("https://example.com/post", "https://other.com/post", "different host"),
    ("https://example.com/p?id=1", "https://example.com/p?id=2", "meaningful parameter"),
    ("http://example.com/p", "https://example.com/p", "scheme is not normalised away"),
    ("https://blog.example.com/p", "https://example.com/p", "subdomains are not stripped"),
]


@pytest.mark.parametrize(("left", "right", "why"), SAME)
def test_urls_that_must_collapse(left: str, right: str, why: str) -> None:
    assert canonical_url(left) == canonical_url(right), why


@pytest.mark.parametrize(("left", "right", "why"), DIFFERENT)
def test_urls_that_must_stay_apart(left: str, right: str, why: str) -> None:
    assert canonical_url(left) != canonical_url(right), why


@pytest.mark.parametrize("value", [None, "", "   ", "ftp://example.com/x", "mailto:a@b.c", "/rel"])
def test_unusable_urls_become_none(value: str | None) -> None:
    assert canonical_url(value) is None


def test_short_hosts_are_not_mangled() -> None:
    """'m.io' must not lose its host to the mobile-prefix rule."""
    assert canonical_url("https://m.io/x") == "https://m.io/x"


def test_item_key_prefers_the_canonical_url() -> None:
    key = item_key(
        source_name="Some feed",
        url="https://example.com/post?utm_source=rss",
        raw_id="guid-1",
        title="A title",
    )
    assert key == "https://example.com/post"


def test_item_key_falls_back_to_the_guid() -> None:
    key = item_key(source_name="Feed", url=None, raw_id="guid-1", title="A title")
    other = item_key(source_name="Feed", url=None, raw_id="guid-2", title="A title")
    assert key.startswith("guid:")
    assert key != other
    # A guid is only unique inside its own feed, so the source name is part of the key.
    assert key != item_key(source_name="Other", url=None, raw_id="guid-1", title="A title")


def test_item_key_falls_back_to_the_title_last() -> None:
    key = item_key(source_name="Feed", url=None, raw_id=None, title="  A   Title ")
    assert key.startswith("title:")
    assert key == item_key(source_name="Feed", url=None, raw_id=None, title="a title")


def test_item_create_normalises_whitespace_and_derives_the_key() -> None:
    item = Item.create(
        source_name="Feed",
        tier=1,
        title="  FastAPI   0.120\n released ",
        url="https://example.com/x/?utm_campaign=a",
        summary="Two\n  sentences.  Here.",
    )
    assert item.title == "FastAPI 0.120 released"
    assert item.summary == "Two sentences. Here."
    assert item.url == "https://example.com/x"
    assert item.key == "https://example.com/x"
    assert item.text.startswith("FastAPI")


def test_item_create_rejects_an_empty_title() -> None:
    with pytest.raises(ValueError, match="without a title"):
        Item.create(source_name="Feed", tier=1, title="   ", url="https://example.com/x")


def test_item_create_rejects_a_naive_timestamp() -> None:
    """A naive timestamp would silently shift the recency decay by up to two hours."""
    with pytest.raises(ValueError, match="timezone-aware"):
        Item.create(
            source_name="Feed",
            tier=1,
            title="t",
            url="https://example.com/x",
            published_at=datetime(2026, 9, 20, 12, 0),
        )


def test_item_engagement_is_read_only() -> None:
    item = Item.create(
        source_name="Feed",
        tier=3,
        title="t",
        url="https://example.com/x",
        engagement={"points": 490.0},
        published_at=datetime(2026, 9, 20, 12, 0, tzinfo=UTC),
    )
    assert item.engagement["points"] == 490.0
    with pytest.raises(TypeError):
        item.engagement["points"] = 1.0  # type: ignore[index]
