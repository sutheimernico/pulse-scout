"""Tests for the key-less JSON adapters.

All payloads here are hand-written and synthetic; the field names mirror the real APIs
(checked against live responses on 2026-09-20) but no captured response is committed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from pulse_scout.sources.json_api import (
    JsonSourceError,
    adapter_for,
    parse_json_source,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
HF_MODELS = "https://huggingface.co/api/models?sort=likes7d"
HF_PAPERS = "https://huggingface.co/api/daily_papers"
HN = "https://hn.algolia.com/api/v1/search?tags=story"
LOBSTERS = "https://lobste.rs/hottest.json"
CISA = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"


def parse(url: str, payload, *, tier: int = 2, window_hours: int = 36):
    return parse_json_source(
        json.dumps(payload).encode("utf-8"),
        url=url,
        source_name="Example source",
        tier=tier,
        now=NOW,
        window_hours=window_hours,
    )


def test_huggingface_models_keep_their_hard_numbers() -> None:
    items = parse(
        HF_MODELS,
        [
            {
                "id": "example-org/Synthetic-7B",
                "likes": 1386,
                "downloads": 1908396,
                "pipeline_tag": "text-generation",
                "createdAt": "2026-09-16T23:40:56.000Z",
            }
        ],
    )
    assert len(items) == 1
    item = items[0]
    assert item.title == "example-org/Synthetic-7B"
    assert item.url == "https://huggingface.co/example-org/Synthetic-7B"
    assert item.engagement == {"likes": 1386.0, "downloads": 1908396.0}
    assert item.published_at == datetime(2026, 9, 16, 23, 40, 56, tzinfo=UTC)


def test_huggingface_models_are_not_time_windowed() -> None:
    """A trending list is a standings table: an old model that is trending today still counts."""
    items = parse(
        HF_MODELS,
        [{"id": "old/model", "likes": 9, "downloads": 9, "createdAt": "2024-01-01T00:00:00.000Z"}],
    )
    assert len(items) == 1


def test_huggingface_papers_keep_the_whole_daily_selection() -> None:
    """The endpoint *is* today's list. Filtering it by each paper's own publication date
    returned nothing at all against the live API on 2026-09-20 — papers reach the daily list
    days after they are published."""
    payload = [
        {
            "title": "A synthetic paper",
            "summary": "Body text.",
            "numComments": 3,
            "publishedAt": "2026-09-20T00:00:00.000Z",
            "paper": {"id": "2609.00001", "upvotes": 45},
        },
        {
            "title": "A paper published earlier, listed today",
            "publishedAt": "2026-09-14T00:00:00.000Z",
            "paper": {"id": "2609.00002", "upvotes": 500},
        },
    ]
    items = parse(HF_PAPERS, payload)
    assert len(items) == 2
    assert items[0].url == "https://huggingface.co/papers/2609.00001"
    assert items[0].engagement == {"upvotes": 45.0, "comments": 3.0}


def test_hacker_news_reads_points_and_comments() -> None:
    payload = {
        "hits": [
            {
                "title": "A synthetic story",
                "url": "https://example.test/story",
                "points": 490,
                "num_comments": 194,
                "objectID": "12345",
                "created_at": "2026-09-20T09:00:00Z",
            }
        ]
    }
    items = parse(HN, payload, tier=3)
    assert items[0].url == "https://example.test/story"
    assert items[0].engagement == {"points": 490.0, "comments": 194.0}
    assert "news.ycombinator.com/item?id=12345" in items[0].summary


def test_hacker_news_text_posts_fall_back_to_the_discussion() -> None:
    payload = {"hits": [{"title": "Ask HN: something", "objectID": "999", "points": 30}]}
    items = parse(HN, payload, tier=3)
    assert items[0].url == "https://news.ycombinator.com/item?id=999"


def test_hacker_news_rejects_a_payload_without_hits() -> None:
    with pytest.raises(JsonSourceError, match="'hits'"):
        parse(HN, {"nbHits": 0})


def test_lobsters_prefers_the_linked_article_over_the_discussion() -> None:
    payload = [
        {
            "title": "A synthetic post",
            "url": "https://example.test/post",
            "comments_url": "https://lobste.rs/s/abc/a",
            "score": 75,
            "comment_count": 18,
            "created_at": "2026-09-19T10:44:52.572-05:00",
            "short_id": "abc",
            "description_plain": "",
        }
    ]
    items = parse(LOBSTERS, payload, tier=3)
    assert items[0].url == "https://example.test/post"
    assert items[0].engagement == {"score": 75.0, "comments": 18.0}


def test_lobsters_self_posts_use_the_discussion_url() -> None:
    payload = [
        {
            "title": "A self post",
            "url": "",
            "comments_url": "https://lobste.rs/s/abc/a",
            "score": 5,
            "created_at": "2026-09-20T08:00:00-05:00",
        }
    ]
    assert parse(LOBSTERS, payload, tier=3)[0].url == "https://lobste.rs/s/abc/a"


def test_cisa_returns_only_entries_added_inside_the_window() -> None:
    """The endpoint ships its whole catalogue every call — 1.716 entries on 2026-09-20."""
    payload = {
        "count": 3,
        "vulnerabilities": [
            {
                "cveID": "CVE-2026-0001",
                "vendorProject": "Example",
                "product": "Thing",
                "vulnerabilityName": "Synthetic flaw",
                "dateAdded": "2026-09-20",
                "shortDescription": "A synthetic description.",
                "knownRansomwareCampaignUse": "Known",
            },
            {"cveID": "CVE-2019-0002", "dateAdded": "2019-01-01"},
            {"cveID": "CVE-2026-0003", "dateAdded": "not a date"},
        ],
    }
    items = parse(CISA, payload, tier=3, window_hours=36)
    assert [item.raw_id for item in items] == ["CVE-2026-0001"]
    assert items[0].engagement == {"ransomware": 1.0}
    assert items[0].url == "https://nvd.nist.gov/vuln/detail/CVE-2026-0001"


def test_cisa_rejects_a_payload_without_vulnerabilities() -> None:
    with pytest.raises(JsonSourceError, match="vulnerabilities"):
        parse(CISA, {"count": 0})


def test_a_non_json_body_is_a_clear_error() -> None:
    with pytest.raises(JsonSourceError, match="not JSON"):
        parse_json_source(b"<html/>", url=LOBSTERS, source_name="x", tier=3, now=NOW)


def test_an_unexpected_top_level_shape_raises_rather_than_returning_nothing() -> None:
    """A silent empty list would shrink the funnel for weeks before anyone noticed."""
    with pytest.raises(JsonSourceError, match="expected a JSON array"):
        parse(LOBSTERS, {"stories": []}, tier=3)


def test_an_unregistered_url_is_refused() -> None:
    with pytest.raises(JsonSourceError, match="no JSON adapter"):
        adapter_for("https://example.test/api/things.json")


def test_rows_without_a_title_are_skipped_not_fatal() -> None:
    items = parse(LOBSTERS, [{"score": 1}, {"title": "kept", "created_at": "2026-09-20T11:00:00Z"}])
    assert [item.title for item in items] == ["kept"]
