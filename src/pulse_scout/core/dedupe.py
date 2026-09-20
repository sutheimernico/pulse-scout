"""Collapsing the same story arriving from several sources.

The spec calls cross-source duplication "simultaneously the strongest importance signal
available", and that is right — five outlets covering one thing is a better relevance signal
than any single outlet's opinion. But the spec gives no method, and there is no labelled data
to tune one against on day one. So this is deliberately the boring version:

1. **Identical canonical URL** — the same page, arriving twice. Certain.
2. **Normalised-title token-set Jaccard ≥ 0,60 inside a 48-hour window** — two headlines about
   the same thing. Judged, not certain.

Conservative on purpose. A false merge silently deletes a story from the digest; a missed merge
only costs a little ranking bonus that the second copy might still earn on its own. Given that
asymmetry, the threshold sits high and the window is short.

There is no cap on how many items may join one cluster: any cap either throws information away
or does nothing. The cap that matters lives in ranking, which stops rewarding a cluster past a
handful of members, so a mega-cluster cannot buy its way to the top.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from pulse_scout.models import Item

DEFAULT_THRESHOLD = 0.60
DEFAULT_WINDOW_HOURS = 48

# Dots and hyphens survive the first pass so that "0.120" does not become "0" and "120";
# a version number is exactly the token that must keep two releases apart.
_PUNCTUATION = re.compile(r"[^\w\s.\-]+", re.UNICODE)
_EDGE_PUNCTUATION = re.compile(r"^[.\-]+|[.\-]+$")
_SITE_PREFIX = re.compile(r"^(show|ask|tell|launch)\s+hn\s*:?\s*", re.IGNORECASE)

# Words that carry no discriminating power in a headline. Versions and numbers are NOT in here:
# "9.9" versus "9.8" is exactly the difference that must keep two releases apart.
_STOPWORDS = frozenset(
    (
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
        "how", "in", "into", "is", "it", "its", "of", "on", "or", "that", "the", "this",
        "to", "was", "what", "when", "why", "with", "you", "your", "we", "our", "will",
        "new", "now", "been",
        "der", "die", "das", "und", "ist", "im", "mit", "von", "für", "den", "dem",
        "ein", "eine", "auf",
    )
)


def normalise_title(title: str) -> frozenset[str]:
    """A headline reduced to the words that distinguish it."""
    stripped = _SITE_PREFIX.sub("", title.strip())
    raw = _PUNCTUATION.sub(" ", stripped.casefold()).split()
    words = [trimmed for word in raw if (trimmed := _EDGE_PUNCTUATION.sub("", word))]
    # Single characters are noise ("a", "I") — except digits, which are the difference
    # between "Python 3" and "Python 4" and must never be thrown away.
    tokens = {
        word
        for word in words
        if word not in _STOPWORDS and (len(word) > 1 or word.isdigit())
    }
    return frozenset(tokens or words)


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    if not intersection:
        return 0.0
    return intersection / len(left | right)


@dataclass(frozen=True, slots=True)
class Cluster:
    """One story, as told by one or more sources."""

    members: tuple[Item, ...]
    reasons: tuple[str, ...] = ()

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def primary(self) -> Item:
        """The member to show.

        The richest description wins, because that is what the writer and the ranking read.
        Ties fall back to input order, so the result never depends on dictionary ordering.
        """
        return max(
            enumerate(self.members),
            key=lambda pair: (len(pair[1].summary), pair[1].url is not None, -pair[0]),
        )[1]

    @property
    def best_tier(self) -> int:
        """The most relevant tier any member came from — tier 1 beats tier 3."""
        return min(item.tier for item in self.members)

    @property
    def source_names(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for item in self.members:
            seen.setdefault(item.source_name, None)
        return tuple(seen)

    @property
    def key(self) -> str:
        return self.primary.key


class _Union:
    """Plain union-find. Single-link agglomeration, and order-independent by construction."""

    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, node: int) -> int:
        while self.parent[node] != node:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def union(self, left: int, right: int) -> bool:
        a, b = self.find(left), self.find(right)
        if a == b:
            return False
        self.parent[max(a, b)] = min(a, b)
        return True


def _within_window(left: Item, right: Item, window: timedelta) -> bool:
    """Undated items are always eligible — most feeds that omit a date are release atoms."""
    if left.published_at is None or right.published_at is None:
        return True
    return abs(left.published_at - right.published_at) <= window


def cluster_items(
    items: Sequence[Item],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    window_hours: int = DEFAULT_WINDOW_HOURS,
) -> list[Cluster]:
    """Group items that tell the same story. Input order is preserved in the output."""
    if not items:
        return []

    window = timedelta(hours=window_hours)
    union = _Union(len(items))
    reasons: dict[int, list[str]] = {}
    tokens = [normalise_title(item.title) for item in items]

    by_key: dict[str, int] = {}
    for index, item in enumerate(items):
        first = by_key.setdefault(item.key, index)
        if first != index and union.union(first, index):
            reasons.setdefault(union.find(first), []).append(f"same url: {item.key}")

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if union.find(i) == union.find(j):
                continue
            left, right = tokens[i], tokens[j]
            # Jaccard can never exceed min/max of the set sizes, so unequal headlines can be
            # rejected without counting anything.
            shorter, longer = sorted((len(left), len(right)))
            if longer == 0 or shorter / longer < threshold:
                continue
            if not _within_window(items[i], items[j], window):
                continue
            score = jaccard(left, right)
            if score >= threshold and union.union(i, j):
                root = union.find(i)
                reasons.setdefault(root, []).append(
                    f"title {score:.2f}: {items[i].title!r} ~ {items[j].title!r}"
                )

    grouped: dict[int, list[int]] = {}
    for index in range(len(items)):
        grouped.setdefault(union.find(index), []).append(index)

    # Sorted by root, which is the lowest member index, so output follows input order.
    return [
        Cluster(
            members=tuple(items[index] for index in indices),
            reasons=tuple(reasons.get(root, ())),
        )
        for root, indices in sorted(grouped.items())
    ]
