#!/usr/bin/env python3
"""Print the five-day observation table (T23) from the stored digests.

    uv run python scripts/observe.py            # the last five digests, oldest first
    uv run python scripts/observe.py --days 10

Paste the output into docs/observations/, then fill the verdict column by hand.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulse_scout.core.observation import HEADER, SEPARATOR, missing_days, row  # noqa: E402
from pulse_scout.store import repo  # noqa: E402
from pulse_scout.store.db import connect  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=5)
    args = parser.parse_args()

    connection = connect()
    dates = sorted(repo.digest_dates(connection, limit=args.days))
    print(HEADER)
    print(SEPARATOR)
    for day in dates:
        print(row(json.loads(repo.digest_for(connection, day)["payload"])))
    all_dates = repo.digest_dates(connection, limit=10_000)
    gaps = missing_days(all_dates, today=datetime.now(ZoneInfo("Europe/Berlin")).date())
    if gaps:
        print(f"\nKein Digest an: {', '.join(gaps)}  (journalctl --user -u pulse-scout.service)")
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
