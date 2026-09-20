#!/usr/bin/env python3
"""Fetch every configured source once and report what actually works.

This is the reality check the source list needs periodically: feeds die, hosts start blocking
key-less clients, and a URL that returned XML in August returns a Cloudflare page in September.
It writes `data/source_health.json` — derived data about our own sources, safe to commit — and
never writes a feed body anywhere except the gitignored cache.

    uv run python scripts/fetch_once.py                 # normal run, aborts on mass failure
    uv run python scripts/fetch_once.py --survey        # never aborts; use when auditing
    uv run python scripts/fetch_once.py --no-cache      # do not keep the raw bodies
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulse_scout.config import load_sources  # noqa: E402
from pulse_scout.sources.cache import RawCache  # noqa: E402
from pulse_scout.sources.collect import (  # noqa: E402
    DEFAULT_WINDOW_HOURS,
    CollectError,
    collect,
)
from pulse_scout.sources.http import UrllibFetcher  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--survey", action="store_true", help="never abort on mass failure")
    parser.add_argument("--no-cache", action="store_true", help="do not keep raw bodies")
    parser.add_argument("--window-hours", type=int, default=DEFAULT_WINDOW_HOURS)
    args = parser.parse_args()

    sources = load_sources()
    now = datetime.now(UTC)
    print(f"fetching {len(sources)} sources ...", flush=True)

    try:
        report = collect(
            sources,
            fetcher=UrllibFetcher(),
            cache=None if args.no_cache else RawCache(),
            now=now,
            window_hours=args.window_hours,
            max_failure_ratio=1.0 if args.survey else 0.30,
        )
    except CollectError as exc:
        print(f"\nABORTED: {exc}", file=sys.stderr)
        return 2

    by_name = {source.name: source for source in sources}
    health = {
        "checked_at": now.isoformat(timespec="seconds"),
        "window_hours": args.window_hours,
        "sources_total": len(sources),
        "items_total": len(report.items),
        # Per tier, because the whole promise is that tier 1 — Nico's own job — reaches him.
        # If tier 1 contributes a handful of items a day, the Pflicht cap cannot rescue it.
        "items_by_tier": {
            str(tier): sum(1 for item in report.items if item.tier == tier)
            for tier in (1, 2, 3)
        },
        "failed": len(report.failed),
        "skipped_fragile": len(report.skipped),
        "unchanged": len(report.unchanged),
        "sources": [
            {
                "name": outcome.source_name,
                "tier": by_name[outcome.source_name].tier,
                "kind": by_name[outcome.source_name].kind,
                "url": by_name[outcome.source_name].url,
                "ok": outcome.ok,
                "items": outcome.item_count,
                "status": outcome.status,
                "elapsed_s": round(outcome.elapsed_s, 2),
                "error": outcome.error,
                "fragile": by_name[outcome.source_name].fragile,
            }
            for outcome in report.outcomes
        ],
    }

    out = ROOT / "data" / "source_health.json"
    out.write_text(json.dumps(health, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\n{report.summary_line()}")
    for outcome in report.outcomes:
        if outcome.ok and outcome.item_count == 0 and not outcome.unchanged:
            print(f"  EMPTY   {outcome.source_name}")
    for outcome in report.skipped:
        print(f"  SKIPPED {outcome.source_name}: {outcome.error}")
    for outcome in report.failed:
        print(f"  FAILED  {outcome.source_name}: {outcome.error}")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
