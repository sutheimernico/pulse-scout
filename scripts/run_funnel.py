#!/usr/bin/env python3
"""Run the deterministic half of the pipeline and print what survived.

No model is involved, so this is fast and can be run as often as needed to see what the
ranking is doing. The candidates it prints are exactly what the scoring pass would receive.

    uv run python scripts/run_funnel.py            # against the real sources
    uv run python scripts/run_funnel.py --top 15   # show more of the ranking
    uv run python scripts/run_funnel.py --explain  # show every factor per candidate
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulse_scout.config import load_sources  # noqa: E402
from pulse_scout.pipeline import run_funnel  # noqa: E402
from pulse_scout.profile import load_profile  # noqa: E402
from pulse_scout.sources.cache import RawCache  # noqa: E402
from pulse_scout.sources.collect import CollectError  # noqa: E402
from pulse_scout.sources.http import UrllibFetcher  # noqa: E402
from pulse_scout.store.db import connect  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=12, help="how many candidates to print")
    parser.add_argument("--explain", action="store_true", help="print every ranking factor")
    parser.add_argument("--db", type=Path, default=None, help="database path")
    args = parser.parse_args()

    sources = load_sources()
    connection = connect(args.db)
    try:
        result = run_funnel(
            connection=connection,
            sources=sources,
            profile=load_profile(),
            fetcher=UrllibFetcher(),
            cache=RawCache(),
        )
    except CollectError as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 2
    finally:
        connection.close()

    counters = result.counters
    print(f"\n{counters.headline()}")
    print(
        f"  {counters.items_seen} seen, {counters.items_new} new, "
        f"{counters.clusters} clusters, {counters.candidates} candidates"
    )
    print(f"  {counters.sources_ok} sources ok, {counters.sources_failed} failed")

    print(f"\ntop {min(args.top, len(result.candidates))} candidates:")
    for position, candidate in enumerate(result.candidates[: args.top], start=1):
        sources_note = (
            f" [{candidate.cluster.size}x: {', '.join(candidate.cluster.source_names)}]"
            if candidate.cluster.size > 1
            else f" [{candidate.cluster.primary.source_name}]"
        )
        print(f"{position:3d}. {candidate.score:6.3f} t{candidate.tier} {candidate.title[:76]}")
        print(f"       {sources_note}")
        if args.explain:
            print(f"       {candidate.explain()}")

    for outcome in result.report.failed:
        print(f"  FAILED {outcome.source_name}: {outcome.error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
