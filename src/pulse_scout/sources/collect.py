"""Driving the whole source list once.

This is where the project's failure policy lives, and it is deliberately asymmetric:

* A source marked `fragile` in the config fails **quietly**. Exactly one Nitter instance worked
  when the list was built, and by 2026-09-20 none did. A source that is known to be unreliable
  must never be able to fail the run.
* Any other source fails **loudly** but locally — the run carries on with the rest.
* If more than 30 % of the non-fragile sources fail, the **whole run** fails. This is the rule
  that matters. A half-empty funnel would still produce a confident-looking digest, and a
  confident digest built on a third of the inputs is precisely the dishonesty this project
  exists to avoid. Better no digest than a quietly impoverished one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from pulse_scout.config import Source
from pulse_scout.models import FetchReport, Item, SourceOutcome
from pulse_scout.sources.cache import RawCache
from pulse_scout.sources.feeds import FeedError, parse_feed
from pulse_scout.sources.http import Fetcher
from pulse_scout.sources.json_api import JsonSourceError, parse_json_source

# Above this share of non-fragile sources failing, the run is not worth trusting.
MAX_FAILURE_RATIO = 0.30

DEFAULT_WINDOW_HOURS = 36

Validators = Mapping[str, tuple[str | None, str | None]]
"""source name -> (etag, last-modified) from the previous run."""


class CollectError(RuntimeError):
    """Too much of the source list is down for the run to mean anything."""


def resolve_url(url: str, *, now: datetime, window_hours: int) -> str:
    """Expand the `{since}` placeholder into a unix timestamp.

    Only Hacker News needs it, and it needs it badly: without a time filter the Algolia
    endpoint hands back the twenty newest submissions, which are minutes old and therefore
    carry no points — destroying the very signal that source is configured for.
    """
    if "{since}" not in url:
        return url
    since = int((now - timedelta(hours=window_hours)).timestamp())
    return url.replace("{since}", str(since))


def _parse(source: Source, body: bytes, *, now: datetime, window_hours: int) -> list[Item]:
    if source.kind == "json":
        return parse_json_source(
            body,
            url=source.url,
            source_name=source.name,
            tier=source.tier,
            now=now,
            window_hours=window_hours,
        )
    return parse_feed(body, source_name=source.name, tier=source.tier)


def collect(
    sources: Sequence[Source],
    *,
    fetcher: Fetcher,
    cache: RawCache | None = None,
    validators: Validators | None = None,
    now: datetime | None = None,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    max_failure_ratio: float = MAX_FAILURE_RATIO,
) -> FetchReport:
    """Fetch, cache and parse every source. Raises only if too much of the list is down."""
    now = now or datetime.now(UTC)
    validators = validators or {}

    items: list[Item] = []
    outcomes: list[SourceOutcome] = []

    for source in sources:
        etag, last_modified = validators.get(source.name, (None, None))
        url = resolve_url(source.url, now=now, window_hours=window_hours)
        result = fetcher.fetch(url, etag=etag, last_modified=last_modified)

        if result.unchanged:
            outcomes.append(
                SourceOutcome(
                    source_name=source.name,
                    ok=True,
                    status=result.status,
                    elapsed_s=result.elapsed_s,
                    unchanged=True,
                    etag=etag,
                    last_modified=last_modified,
                )
            )
            continue

        if not result.ok:
            outcomes.append(
                SourceOutcome(
                    source_name=source.name,
                    ok=False,
                    status=result.status or None,
                    elapsed_s=result.elapsed_s,
                    error=result.error or "fetch failed",
                    skipped=source.tolerates_failure,
                )
            )
            continue

        if cache is not None:
            cache.store(source.name, result.body, kind=source.kind, when=now.date())

        try:
            parsed = _parse(source, result.body, now=now, window_hours=window_hours)
        except (FeedError, JsonSourceError, ValueError) as exc:
            outcomes.append(
                SourceOutcome(
                    source_name=source.name,
                    ok=False,
                    status=result.status,
                    elapsed_s=result.elapsed_s,
                    error=f"{type(exc).__name__}: {exc}",
                    skipped=source.tolerates_failure,
                )
            )
            continue

        items.extend(parsed)
        outcomes.append(
            SourceOutcome(
                source_name=source.name,
                ok=True,
                item_count=len(parsed),
                status=result.status,
                elapsed_s=result.elapsed_s,
                etag=result.etag,
                last_modified=result.last_modified,
            )
        )

    report = FetchReport(items=items, outcomes=outcomes)
    _guard_failure_ratio(report, sources, max_failure_ratio)
    return report


def _guard_failure_ratio(
    report: FetchReport, sources: Sequence[Source], max_failure_ratio: float
) -> None:
    expected = [source for source in sources if not source.tolerates_failure]
    if not expected:
        return
    ratio = len(report.failed) / len(expected)
    if ratio > max_failure_ratio:
        names = ", ".join(f"{o.source_name} ({o.error})" for o in report.failed[:5])
        raise CollectError(
            f"{len(report.failed)} of {len(expected)} non-fragile sources failed "
            f"({ratio:.0%} > {max_failure_ratio:.0%}). Refusing to build a digest from a "
            f"crippled funnel. First failures: {names}"
        )
