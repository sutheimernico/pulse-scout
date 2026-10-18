"""The five-day observation (T23): one table row per stored digest, from the record itself.

Every machine column comes from what the build stored — nothing is re-measured or estimated
afterwards. The verdict column stays empty: that one is Nico's, and only his.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any

HEADER = (
    "| Datum | Stand | gesichtet | neu | Kandidaten | Karten | Lesezeit | Laufzeit "
    "| Scorer unlesbar | Rang-Korrelation | Faktencheck verworfen | Originaltext-Karten "
    "| Quellen ausgefallen | Urteil (Nico) |"
)
SEPARATOR = "|" + "---|" * (HEADER.count("|") - 1)


def _minutes(seconds: object) -> str:
    if not isinstance(seconds, int | float):
        return "–"
    minutes, rest = divmod(int(round(seconds)), 60)
    return f"{minutes}:{rest:02d}"


def row(payload: Mapping[str, Any]) -> str:
    counters = payload.get("counters", {})
    stats = payload.get("stats", {})
    scoring = stats.get("scoring", {}) if isinstance(stats, Mapping) else {}
    guard = payload.get("guard", {})

    if scoring.get("skipped"):
        unreadable = correlation = "übersprungen"
    else:
        unreadable = str(scoring.get("parse_failures", "–"))
        value = scoring.get("rank_correlation")
        correlation = f"{value:.2f}" if isinstance(value, int | float) else "–"

    rejected = (
        f"{guard['rejected']}/{guard['checked']}" if "checked" in guard else "vor dem Check"
    )
    cells = [
        payload.get("digest_date", "?"),
        str(payload.get("generated_at", ""))[11:16],
        str(counters.get("items_seen", "–")),
        str(counters.get("items_new", "–")),
        str(counters.get("candidates", "–")),
        str(len(payload.get("cards", []))),
        _minutes(payload.get("read_seconds")),
        _minutes(stats.get("total_seconds") if isinstance(stats, Mapping) else None),
        unreadable,
        correlation,
        rejected,
        str(guard.get("quoted_cards", "–")),
        str(counters.get("sources_failed", "–")),
        "",
    ]
    return "| " + " | ".join(cells) + " |"


def missing_days(digest_dates: Iterable[str], *, today: date) -> list[str]:
    """Days without a digest, from the first stored one through `today`.

    Five consecutive mornings is the acceptance test, so a gap is the finding that matters
    most and must not hide between two table rows.
    """
    present = {date.fromisoformat(d) for d in digest_dates}
    if not present:
        return []
    day = min(present)
    gaps: list[str] = []
    while day <= today:
        if day not in present:
            gaps.append(day.isoformat())
        day += timedelta(days=1)
    return gaps
