#!/usr/bin/env python3
"""Build today's digest: the whole pipeline, end to end.

    uv run python scripts/build_digest.py                # the real thing, minutes of CPU
    uv run python scripts/build_digest.py --skip-scoring # deterministic ranking only, faster
    uv run python scripts/build_digest.py --dry-run      # funnel only, no model at all

Exits non-zero and writes nothing if the model produces something that does not check out.
That is the specified behaviour: yesterday's digest stays the latest one rather than being
replaced by something plausible.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulse_scout.config import load_sources  # noqa: E402
from pulse_scout.core import digest as digest_module  # noqa: E402
from pulse_scout.core.selection import FINALIST_COUNT, select  # noqa: E402
from pulse_scout.core.validate import DigestRejected  # noqa: E402
from pulse_scout.llm.ollama import OllamaClient  # noqa: E402
from pulse_scout.llm.scorer import ScoredCandidate, ScoringResult, score_candidates  # noqa: E402
from pulse_scout.llm.writer import WriterError, write_digest  # noqa: E402
from pulse_scout.pipeline import run_funnel  # noqa: E402
from pulse_scout.profile import load_profile  # noqa: E402
from pulse_scout.sources.cache import RawCache  # noqa: E402
from pulse_scout.sources.collect import CollectError  # noqa: E402
from pulse_scout.sources.http import UrllibFetcher  # noqa: E402
from pulse_scout.store import repo  # noqa: E402
from pulse_scout.store.db import connect  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="funnel only, no model")
    parser.add_argument("--skip-scoring", action="store_true", help="skip the 1.5b pass")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--output-cap", type=int, default=700)
    args = parser.parse_args()

    now = datetime.now(UTC)
    connection = connect(args.db)
    started = time.monotonic()

    try:
        funnel = run_funnel(
            connection=connection,
            sources=load_sources(),
            profile=load_profile(),
            fetcher=UrllibFetcher(),
            cache=RawCache(),
            now=now,
        )
    except CollectError as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        connection.close()
        return 2

    print(f"funnel: {funnel.counters.headline()} in {time.monotonic() - started:.0f}s")
    if not funnel.candidates:
        print("nothing new today — no digest written", file=sys.stderr)
        connection.close()
        return 1
    if args.dry_run:
        connection.close()
        return 0

    client = OllamaClient()
    notes: list[str] = []

    if args.skip_scoring:
        # Deterministic order only. Honest about it: the note reaches the digest.
        scoring = ScoringResult(
            scored=[
                ScoredCandidate(candidate=candidate, deterministic_rank=position)
                for position, candidate in enumerate(funnel.candidates, start=1)
            ]
        )
        notes.append("Ohne Modell-Bewertung gebaut — Reihenfolge rein deterministisch.")
    else:
        scoring = score_candidates(funnel.candidates, client=client)
        print(
            f"scoring: {len(scoring.scored)} rated in {scoring.seconds:.0f}s, "
            f"{scoring.parse_failures} unparseable, "
            f"rank correlation {scoring.rank_correlation}"
        )
        if scoring.parse_failures:
            notes.append(
                f"{scoring.parse_failures} von {len(scoring.scored)} Bewertungen waren "
                f"nicht lesbar — diese Einträge behalten ihre Platzierung aus dem Ranking."
            )

    finalists = scoring.finalists(FINALIST_COUNT)
    selection = select(finalists, [e for e in scoring.scored if e not in finalists])

    try:
        draft = write_digest(finalists, client=client, now=now, output_cap=args.output_cap)
    except (DigestRejected, WriterError) as exc:
        print(f"\nNO DIGEST: {exc}", file=sys.stderr)
        connection.close()
        return 3

    print(f"writing: {draft.output_tokens} tokens in {draft.seconds:.0f}s")

    digest = digest_module.build(
        selection=selection,
        draft=draft,
        counters=funnel.counters,
        now=now,
        extra_notes=notes,
    )
    repo.save_digest(
        connection,
        digest_date=digest.digest_date,
        generated_at=digest.generated_at,
        payload=digest.to_json(),
        read_seconds=digest.read_seconds,
        card_count=len(digest.cards),
        run_id=funnel.run_id,
    )

    out_dir = ROOT / "data" / "digests"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{digest.digest_date}.md"
    path.write_text(digest_module.render_markdown(digest), encoding="utf-8")

    minutes, seconds = divmod(digest.read_seconds, 60)
    print(
        f"\n{digest.funnel_line} · {minutes}:{seconds:02d} Lesezeit"
        f"{' · ÜBER BUDGET' if digest.over_budget else ''}"
    )
    print(f"wrote {path.relative_to(ROOT)} after {time.monotonic() - started:.0f}s total")
    connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
