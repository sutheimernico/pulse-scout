"""Adapters for the five key-less JSON APIs.

These are the sources that ship a *number* rather than an announcement — Hacker News points,
Lobsters score, HuggingFace likes and downloads, paper upvotes. That is why they are worth
their own code path: the funnel's first cut is deterministic, and it needs hard signals to cut
on. A press release cannot tell you whether a model is strong; 1,9 million downloads can.

Two rules for everything in here:

* **An unrecognised payload raises.** Returning an empty list when an API changes shape would
  quietly shrink the funnel for weeks before anybody noticed, and a quietly wrong digest is
  the one failure mode this project cannot afford.
* **Snapshots are windowed here, not later.** HuggingFace returns the same 50 models every day
  and CISA returns its entire 1.716-entry catalogue on every call. Filtering to the current
  window at the adapter is what stops the funnel from re-litigating the same items daily.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from pulse_scout.models import Item
from pulse_scout.sources.feeds import clean_text, parse_timestamp

DEFAULT_WINDOW_HOURS = 72


class JsonSourceError(ValueError):
    """The payload is not the shape this adapter knows. Always loud."""


def _load(body: bytes, source_name: str) -> Any:
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise JsonSourceError(f"{source_name}: body is not JSON ({exc})") from exc


def _require_list(payload: Any, source_name: str) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise JsonSourceError(
            f"{source_name}: expected a JSON array, got {type(payload).__name__}"
        )
    rows = [row for row in payload if isinstance(row, dict)]
    if payload and not rows:
        raise JsonSourceError(f"{source_name}: array contains no objects")
    return rows


def _number(row: Mapping[str, Any], key: str) -> float:
    value = row.get(key)
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _in_window(when: datetime | None, *, now: datetime, window_hours: int) -> bool:
    """Undated rows are kept: the seen-set upstream decides whether they are new."""
    if when is None:
        return True
    return when >= now - timedelta(hours=window_hours)


def huggingface_models(
    body: bytes, *, source_name: str, tier: int, now: datetime, window_hours: int
) -> list[Item]:
    """Trending models. The list is a standings table, so no time window is applied.

    Sorting by creation date instead would return hobbyist uploads with zero downloads — the
    source list says so explicitly, and it is right.
    """
    items = []
    for row in _require_list(_load(body, source_name), source_name):
        model_id = row.get("id") or row.get("modelId")
        if not isinstance(model_id, str) or not model_id:
            continue
        likes = _number(row, "likes")
        downloads = _number(row, "downloads")
        pipeline = row.get("pipeline_tag")
        summary = f"{pipeline} model" if isinstance(pipeline, str) and pipeline else "model"
        items.append(
            Item.create(
                source_name=source_name,
                tier=tier,
                title=model_id,
                url=f"https://huggingface.co/{model_id}",
                summary=f"{summary}, {int(likes)} likes and {int(downloads)} downloads.",
                published_at=parse_timestamp(row.get("createdAt")),
                engagement={"likes": likes, "downloads": downloads},
                raw_id=model_id,
            )
        )
    return items


def huggingface_papers(
    body: bytes, *, source_name: str, tier: int, now: datetime, window_hours: int
) -> list[Item]:
    """The curated daily paper list — the reason arXiv itself is deliberately absent.

    Not time-windowed, for the same reason the model list is not: this endpoint *is* today's
    selection. Filtering it by each paper's own publication date returned nothing at all on
    2026-09-20, because a paper reaches the daily list days after it is published.
    """
    items = []
    for row in _require_list(_load(body, source_name), source_name):
        paper = row.get("paper")
        paper = paper if isinstance(paper, dict) else {}
        title = row.get("title") or paper.get("title")
        paper_id = paper.get("id")
        if not isinstance(title, str) or not title.strip():
            continue
        published = parse_timestamp(row.get("publishedAt") or paper.get("publishedAt"))
        items.append(
            Item.create(
                source_name=source_name,
                tier=tier,
                title=title,
                url=f"https://huggingface.co/papers/{paper_id}" if paper_id else None,
                summary=clean_text(row.get("summary") or paper.get("summary")),
                published_at=published,
                engagement={
                    "upvotes": _number(paper, "upvotes"),
                    "comments": _number(row, "numComments"),
                },
                raw_id=str(paper_id) if paper_id else None,
            )
        )
    return items


def hacker_news(
    body: bytes, *, source_name: str, tier: int, now: datetime, window_hours: int
) -> list[Item]:
    """Algolia's search response. The strongest generic relevance signal available for free."""
    payload = _load(body, source_name)
    if not isinstance(payload, dict) or "hits" not in payload:
        raise JsonSourceError(f"{source_name}: expected an object with 'hits'")
    items = []
    for row in _require_list(payload["hits"], source_name):
        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        object_id = row.get("objectID")
        discussion = f"https://news.ycombinator.com/item?id={object_id}" if object_id else None
        published = parse_timestamp(row.get("created_at"))
        if not _in_window(published, now=now, window_hours=window_hours):
            continue
        items.append(
            Item.create(
                source_name=source_name,
                tier=tier,
                # A text post ("Ask HN") has no url of its own; the discussion is the item.
                url=row.get("url") or discussion,
                title=title,
                summary=f"Hacker News discussion: {discussion}" if discussion else "",
                published_at=published,
                engagement={
                    "points": _number(row, "points"),
                    "comments": _number(row, "num_comments"),
                },
                raw_id=str(object_id) if object_id else None,
            )
        )
    return items


def lobsters(
    body: bytes, *, source_name: str, tier: int, now: datetime, window_hours: int
) -> list[Item]:
    items = []
    for row in _require_list(_load(body, source_name), source_name):
        title = row.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        published = parse_timestamp(row.get("created_at"))
        if not _in_window(published, now=now, window_hours=window_hours):
            continue
        items.append(
            Item.create(
                source_name=source_name,
                tier=tier,
                title=title,
                url=row.get("url") or row.get("comments_url") or row.get("short_id_url"),
                summary=clean_text(row.get("description_plain") or row.get("description")),
                published_at=published,
                engagement={
                    "score": _number(row, "score"),
                    "comments": _number(row, "comment_count"),
                },
                raw_id=row.get("short_id"),
            )
        )
    return items


def cisa_kev(
    body: bytes, *, source_name: str, tier: int, now: datetime, window_hours: int
) -> list[Item]:
    """Known exploited vulnerabilities.

    This endpoint has no "new today" view — it returns the whole catalogue (1.716 entries on
    2026-09-20). Without the `dateAdded` filter the security category would swamp the funnel
    every single day.
    """
    payload = _load(body, source_name)
    if not isinstance(payload, dict) or "vulnerabilities" not in payload:
        raise JsonSourceError(f"{source_name}: expected an object with 'vulnerabilities'")
    cutoff = (now - timedelta(hours=window_hours)).date()
    items = []
    for row in _require_list(payload["vulnerabilities"], source_name):
        cve = row.get("cveID")
        if not isinstance(cve, str) or not cve.strip():
            continue
        added = row.get("dateAdded")
        try:
            added_date = datetime.fromisoformat(str(added)).date()
        except (TypeError, ValueError):
            continue
        if added_date < cutoff:
            continue
        vendor = row.get("vendorProject") or ""
        product = row.get("product") or ""
        name = row.get("vulnerabilityName") or cve
        ransomware = str(row.get("knownRansomwareCampaignUse", "")).lower() == "known"
        items.append(
            Item.create(
                source_name=source_name,
                tier=tier,
                title=f"{cve}: {vendor} {product} — {name}".strip(),
                url=f"https://nvd.nist.gov/vuln/detail/{cve}",
                summary=clean_text(row.get("shortDescription")),
                published_at=datetime.combine(added_date, datetime.min.time(), tzinfo=UTC),
                engagement={"ransomware": 1.0 if ransomware else 0.0},
                raw_id=cve,
            )
        )
    return items


Adapter = Callable[..., list[Item]]

# Matched on a substring of the configured URL. Explicit rather than clever: a new JSON source
# must be registered here on purpose, so nobody adds one and wonders why it produces nothing.
_ADAPTERS: Sequence[tuple[str, Adapter]] = (
    ("huggingface.co/api/daily_papers", huggingface_papers),
    ("huggingface.co/api/models", huggingface_models),
    ("hn.algolia.com/api", hacker_news),
    ("lobste.rs", lobsters),
    ("cisa.gov", cisa_kev),
)


def adapter_for(url: str) -> Adapter:
    for marker, adapter in _ADAPTERS:
        if marker in url:
            return adapter
    raise JsonSourceError(f"no JSON adapter registered for {url}")


def parse_json_source(
    body: bytes,
    *,
    url: str,
    source_name: str,
    tier: int,
    now: datetime | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> list[Item]:
    """Parse a JSON source body with the adapter registered for its URL."""
    return adapter_for(url)(
        body,
        source_name=source_name,
        tier=tier,
        now=now or datetime.now(UTC),
        window_hours=window_hours,
    )
