#!/usr/bin/env python3
"""Build today's digest: the whole pipeline, end to end.

    uv run python scripts/build_digest.py                # the real thing, minutes of CPU
    uv run python scripts/build_digest.py --skip-scoring # deterministic ranking only, faster
    uv run python scripts/build_digest.py --dry-run      # funnel only, no model at all
    uv run python scripts/build_digest.py --skip-if-built  # what the daily timer runs

Exits non-zero and writes nothing if the model produces something that does not check out.
That is the specified behaviour: yesterday's digest stays the latest one rather than being
replaced by something plausible.

Every headline and body sentence is then checked against its source by a second model pass;
what the source does not support is dropped before anything is stored.
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
from pulse_scout.llm.verifier import guard  # noqa: E402
from pulse_scout.llm.writer import WriterError, write_digest  # noqa: E402
from pulse_scout.pipeline import digest_already_built, run_funnel  # noqa: E402
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
    parser.add_argument(
        "--skip-if-built", action="store_true", help="exit 0 if today's digest already exists"
    )
    args = parser.parse_args()

    now = datetime.now(UTC)
    connection = connect(args.db)
    started = time.monotonic()

    if args.skip_if_built and digest_already_built(connection, now=now):
        print("today's digest already exists — nothing to do")
        connection.close()
        return 0

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

    funnel_seconds = time.monotonic() - started
    print(f"funnel: {funnel.counters.headline()} in {funnel_seconds:.0f}s", flush=True)
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
        scoring_stats: dict[str, object] = {"skipped": True}
    else:
        scoring = score_candidates(funnel.candidates, client=client)
        print(
            f"scoring: {len(scoring.scored)} rated in {scoring.seconds:.0f}s, "
            f"{scoring.parse_failures} unparseable, "
            f"rank correlation {scoring.rank_correlation}",
            flush=True,
        )
        scoring_stats = {
            "rated": len(scoring.scored),
            "parse_failures": scoring.parse_failures,
            "call_failures": scoring.call_failures,
            "rank_correlation": scoring.rank_correlation,
            "seconds": round(scoring.seconds, 1),
        }
        if scoring.parse_failures:
            notes.append(
                f"{scoring.parse_failures} von {len(scoring.scored)} Bewertungen waren "
                f"nicht lesbar — diese Einträge behalten ihre Platzierung aus dem Ranking."
            )

    finalists = scoring.finalists(FINALIST_COUNT)
    # Compared by cluster key rather than by value: a ScoredCandidate carries the whole
    # cluster, so `in` would deep-compare every item on every lookup.
    chosen = {e.candidate.cluster.key for e in finalists}
    selection = select(
        finalists, [e for e in scoring.scored if e.candidate.cluster.key not in chosen]
    )
    print(f"writing: {len(finalists)} finalists to qwen2.5:7b ...", flush=True)

    try:
        draft = write_digest(finalists, client=client, now=now, output_cap=args.output_cap)
    except (DigestRejected, WriterError) as exc:
        print(f"\nNO DIGEST: {exc}", file=sys.stderr)
        connection.close()
        return 3

    print(f"  {draft.output_tokens} tokens in {draft.seconds:.0f}s "
          f"(attempt {draft.attempts})", flush=True)

    # Every headline and body sentence is put back to the model against its source. What the
    # source does not support is dropped — the reader never sees the unchecked draft.
    print("checking: every factual sentence against its source ...", flush=True)
    try:
        checked = guard(draft.judgements, draft.items, client=client)
    except WriterError as exc:
        print(f"\nNO DIGEST: {exc}", file=sys.stderr)
        connection.close()
        return 3
    print(
        f"  {checked.checked} checked, {checked.rejected} rejected, "
        f"{len(checked.quoted)} cards fell back to the source text, in {checked.seconds:.0f}s",
        flush=True,
    )

    digest = digest_module.build(
        selection=selection,
        draft=draft,
        counters=funnel.counters,
        now=now,
        extra_notes=notes,
        guard=checked,
        stats={
            "funnel_seconds": round(funnel_seconds, 1),
            "scoring": scoring_stats,
            "writing": {
                "seconds": round(draft.seconds, 1),
                "output_tokens": draft.output_tokens,
                "attempts": draft.attempts,
            },
            "total_seconds": round(time.monotonic() - started, 1),
        },
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
