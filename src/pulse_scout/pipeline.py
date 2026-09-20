"""The funnel, wired together. Fetch → seen-filter → cluster → rank.

No model is involved at any point here, which is the design's main idea: by the time the 7B
model is asked for anything, 95 % of the decisions have already been made by code that can be
read, tested and explained.

The counters this produces are the ones the screen shows (`569 gesichtet → 5 für dich`). They
are real measurements of this run, never estimates — the filter ratio is the product's whole
promise, so a decorative number there would undermine everything else.

**Clustering sees only the items that are new in this run.** A story that arrives from one
source today and another tomorrow will therefore not be merged. That is a known limitation and
the right one for stage 1: linking across days is exactly what stage 2's embeddings are for,
and faking it here with a widening window would double-report stories Nico already read.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pulse_scout.config import Source
from pulse_scout.core.dedupe import cluster_items
from pulse_scout.core.ranking import Candidate, rank
from pulse_scout.models import FetchReport
from pulse_scout.profile import Profile
from pulse_scout.sources.cache import RawCache
from pulse_scout.sources.collect import DEFAULT_WINDOW_HOURS, collect
from pulse_scout.sources.http import Fetcher
from pulse_scout.store import repo

DEFAULT_CANDIDATE_LIMIT = 40


@dataclass(frozen=True, slots=True)
class FunnelCounters:
    """What the funnel actually did. Every number is counted, not estimated."""

    items_seen: int
    items_new: int
    clusters: int
    candidates: int
    sources_ok: int
    sources_failed: int

    def as_counters(self) -> dict[str, int]:
        return {
            "items_seen": self.items_seen,
            "items_new": self.items_new,
            "clusters": self.clusters,
            "candidates": self.candidates,
            "sources_ok": self.sources_ok,
            "sources_failed": self.sources_failed,
        }

    def headline(self) -> str:
        """The line the header shows, in German, with the real numbers."""
        return f"{self.items_seen} gesichtet → {self.candidates} Kandidaten"


@dataclass(frozen=True, slots=True)
class FunnelResult:
    run_id: int
    candidates: list[Candidate]
    counters: FunnelCounters
    report: FetchReport


def run_funnel(
    *,
    connection: sqlite3.Connection,
    sources: Sequence[Source],
    profile: Profile,
    fetcher: Fetcher,
    cache: RawCache | None = None,
    now: datetime | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> FunnelResult:
    """One deterministic pass from the source list to the ranked candidates."""
    now = now or datetime.now(UTC)
    run_id = repo.start_run(connection, now=now)

    report = collect(
        sources,
        fetcher=fetcher,
        cache=cache,
        validators=repo.validators(connection),
        now=now,
        window_hours=window_hours,
    )
    repo.record_outcomes(connection, report.outcomes, now=now)

    fresh = repo.record_seen(connection, report.items, now=now)
    clusters = cluster_items(fresh)
    by_name = {source.name: source for source in sources}
    candidates = rank(
        clusters, sources=by_name, profile=profile, now=now, limit=candidate_limit
    )

    counters = FunnelCounters(
        items_seen=len(report.items),
        items_new=len(fresh),
        clusters=len(clusters),
        candidates=len(candidates),
        sources_ok=len(report.outcomes) - len(report.failed),
        sources_failed=len(report.failed),
    )
    repo.finish_run(
        connection,
        run_id,
        now=datetime.now(UTC) if now is None else now,
        counters=counters.as_counters(),
        notes=report.summary_line(),
    )
    return FunnelResult(
        run_id=run_id, candidates=candidates, counters=counters, report=report
    )
