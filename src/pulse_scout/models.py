"""The shapes that travel through the pipeline.

Everything here is frozen. Each pipeline stage returns new objects rather than mutating the
ones it was handed, so a stage can always be re-run on the same input and a test can always
compare before and after.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from pulse_scout.core.canonical import canonical_url, item_key

_NO_ENGAGEMENT: Mapping[str, float] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class Item:
    """One thing a source told us about, normalised.

    `engagement` holds whatever hard numbers the source ships with — Hacker News points,
    Lobsters score, HuggingFace likes and downloads. The values are only comparable *within*
    one source (a HuggingFace like is not a HN point), which is why ranking normalises per
    source rather than across the corpus.
    """

    key: str
    source_name: str
    tier: int
    title: str
    url: str | None = None
    summary: str = ""
    published_at: datetime | None = None
    engagement: Mapping[str, float] = _NO_ENGAGEMENT
    raw_id: str | None = None

    @classmethod
    def create(
        cls,
        *,
        source_name: str,
        tier: int,
        title: str,
        url: str | None = None,
        summary: str = "",
        published_at: datetime | None = None,
        engagement: Mapping[str, float] | None = None,
        raw_id: str | None = None,
    ) -> Item:
        """Build an item and derive its identity. The only supported way to make one."""
        clean_title = " ".join(title.split())
        if not clean_title:
            raise ValueError(f"{source_name}: item without a title (url={url!r})")
        if published_at is not None and published_at.tzinfo is None:
            raise ValueError(f"{source_name}: published_at must be timezone-aware")
        return cls(
            key=item_key(source_name=source_name, url=url, raw_id=raw_id, title=clean_title),
            source_name=source_name,
            tier=tier,
            title=clean_title,
            url=canonical_url(url),
            summary=" ".join(summary.split()),
            published_at=published_at,
            engagement=MappingProxyType(dict(engagement)) if engagement else _NO_ENGAGEMENT,
            raw_id=raw_id,
        )

    @property
    def text(self) -> str:
        """Title plus summary — what ranking, scoring and validation all read."""
        return f"{self.title}\n{self.summary}".strip()
