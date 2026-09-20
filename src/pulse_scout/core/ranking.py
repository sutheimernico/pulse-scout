"""The deterministic cut: ~570 clusters down to ~40 candidates, with no model involved.

This is where the funnel does its real work. The language model never sees 95 % of what comes
in, and the reason is not only throughput — it is that every factor here is inspectable,
testable and cheap, while a model's opinion is none of the three.

The formula is one line and every constant lives in `data/profile.toml`:

    score = source_weight · tier_bonus · engagement · keywords · negatives · recency · duplicates

Each factor is computed separately and kept on the candidate, so "why is this in my digest?"
has an answer that is a table rather than a shrug.

Engagement is normalised **within its own source**. A HuggingFace like and a Hacker News point
are not the same unit and never will be; ranking one against the other directly would mean the
source with the largest numbers wins every day.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from pulse_scout.config import Source
from pulse_scout.core.dedupe import Cluster
from pulse_scout.profile import Profile

# Which engagement number a source's items are ranked on, in order of preference. A source
# reports at most one of these, so the order only decides ties in theory.
_SIGNAL_KEYS = ("points", "score", "upvotes", "likes", "downloads", "ransomware")


@dataclass(frozen=True, slots=True)
class Candidate:
    """One cluster with its score and the reason for it."""

    cluster: Cluster
    score: float
    factors: Mapping[str, float] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return self.cluster.primary.title

    @property
    def tier(self) -> int:
        return self.cluster.best_tier

    def explain(self) -> str:
        parts = ", ".join(f"{name} {value:.2f}" for name, value in sorted(self.factors.items()))
        return f"{self.score:.3f} = {parts}"


def _signal_value(engagement: Mapping[str, float]) -> float | None:
    for key in _SIGNAL_KEYS:
        if key in engagement:
            return engagement[key]
    return None


def engagement_percentiles(
    clusters: Sequence[Cluster],
) -> dict[tuple[str, str], float]:
    """Rank each item's engagement number against the others from the same source.

    Returns (source name, item key) -> 0..1. Sources that ship no numbers are absent, and
    their items get the neutral factor rather than a zero — "no signal" is not "bad signal".
    """
    by_source: dict[str, list[tuple[str, float]]] = {}
    for cluster in clusters:
        for item in cluster.members:
            value = _signal_value(item.engagement)
            if value is not None:
                by_source.setdefault(item.source_name, []).append((item.key, value))

    percentiles: dict[tuple[str, str], float] = {}
    for source_name, entries in by_source.items():
        if len(entries) == 1:
            # A single measured item has nothing to be ranked against. Treat it as mid-field
            # rather than best-in-class, which would hand every low-volume source the top slot.
            percentiles[(source_name, entries[0][0])] = 0.5
            continue
        ordered = sorted(entries, key=lambda pair: pair[1])
        last = len(ordered) - 1
        for position, (key, _value) in enumerate(ordered):
            percentiles[(source_name, key)] = position / last
    return percentiles


def recency_factor(published_at: datetime | None, *, now: datetime, profile: Profile) -> float:
    if published_at is None:
        return profile.recency_undated
    age_hours = max(0.0, (now - published_at).total_seconds() / 3600.0)
    decayed = 0.5 ** (age_hours / profile.recency_half_life_hours)
    return max(profile.recency_floor, min(1.0, decayed))


def score_cluster(
    cluster: Cluster,
    *,
    sources: Mapping[str, Source],
    profile: Profile,
    percentiles: Mapping[tuple[str, str], float],
    now: datetime,
) -> Candidate:
    """Score one cluster and keep the breakdown."""
    weights = [sources[item.source_name].weight for item in cluster.members]
    source_weight = max(weights) if weights else 1.0

    tier_bonus = profile.tier_bonus[cluster.best_tier]

    measured = [
        percentiles[(item.source_name, item.key)]
        for item in cluster.members
        if (item.source_name, item.key) in percentiles
    ]
    engagement = 1.0 + profile.engagement * max(measured) if measured else 1.0

    # Every member's headline counts, because the keyword may only appear in one source's
    # phrasing of the story; only the primary's summary counts, to keep this bounded.
    text = "\n".join(item.title for item in cluster.members) + "\n" + cluster.primary.summary
    positive, negative_hits = profile.keyword_score(text)
    keywords = 1.0 + profile.keyword * positive
    negatives = profile.negative_penalty if negative_hits and positive < 2.0 else 1.0

    newest = [item.published_at for item in cluster.members if item.published_at is not None]
    recency = recency_factor(max(newest) if newest else None, now=now, profile=profile)

    extra = min(cluster.size - 1, profile.duplicate_cap)
    duplicates = 1.0 + profile.duplicate * extra

    factors = {
        "source": source_weight,
        "tier": tier_bonus,
        "engagement": engagement,
        "keywords": keywords,
        "negatives": negatives,
        "recency": recency,
        "duplicates": duplicates,
    }
    score = 1.0
    for value in factors.values():
        score *= value
    return Candidate(cluster=cluster, score=score, factors=factors)


def rank(
    clusters: Sequence[Cluster],
    *,
    sources: Mapping[str, Source],
    profile: Profile,
    now: datetime,
    limit: int | None = None,
) -> list[Candidate]:
    """Score every cluster and return the best ones, highest first.

    Ties break on the cluster key so that two runs over the same data produce the same order —
    a digest that reshuffles itself between runs cannot be debugged.
    """
    percentiles = engagement_percentiles(clusters)
    candidates = [
        score_cluster(
            cluster, sources=sources, profile=profile, percentiles=percentiles, now=now
        )
        for cluster in clusters
    ]
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.cluster.key))
    return candidates[:limit] if limit else candidates
