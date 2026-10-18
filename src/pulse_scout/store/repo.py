"""Queries. The pipeline talks to the database only through these functions.

The one that matters is `record_seen`: it is the difference between a funnel and a treadmill.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

from pulse_scout.models import Item, SourceOutcome


def _stamp(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


def record_seen(
    connection: sqlite3.Connection, items: Sequence[Item], *, now: datetime
) -> list[Item]:
    """Persist every item and return only the ones never seen before.

    An item already in the table has its `last_seen` bumped and is dropped from the return
    value. That is the whole mechanism by which 569 fetched items become a handful of new
    ones — everything downstream assumes it has already happened.

    Items repeated inside one batch are collapsed too, so a story arriving from two sources
    with the same canonical URL counts once.
    """
    fresh: list[Item] = []
    stamp = _stamp(now)
    seen_in_batch: set[str] = set()

    for item in items:
        if item.key in seen_in_batch:
            continue
        seen_in_batch.add(item.key)

        cursor = connection.execute(
            """
            INSERT INTO items (item_key, source_name, tier, title, url, summary,
                               published_at, engagement, raw_id, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_key) DO UPDATE SET last_seen = excluded.last_seen
            """,
            (
                item.key,
                item.source_name,
                item.tier,
                item.title,
                item.url,
                item.summary,
                _stamp(item.published_at) if item.published_at else None,
                json.dumps(dict(item.engagement), sort_keys=True),
                item.raw_id,
                stamp,
                stamp,
            ),
        )
        # An INSERT that turned into an UPDATE leaves first_seen alone, so comparing the two
        # is a reliable "is this new?" — more reliable than rowcount, which counts both.
        row = connection.execute(
            "SELECT first_seen FROM items WHERE item_key = ?", (item.key,)
        ).fetchone()
        if row["first_seen"] == stamp and cursor.rowcount:
            fresh.append(item)

    connection.commit()
    return fresh


def forget_items_first_seen_at(connection: sqlite3.Connection, *, now: datetime) -> int:
    """Un-see the items a run recorded as new, because that run produced no digest.

    `first_seen` carries the run's logical start, so it identifies exactly this run's new
    items. Returns how many were removed.
    """
    cursor = connection.execute("DELETE FROM items WHERE first_seen = ?", (_stamp(now),))
    connection.commit()
    return cursor.rowcount


def count_items(connection: sqlite3.Connection) -> int:
    return connection.execute("SELECT COUNT(*) FROM items").fetchone()[0]


def validators(connection: sqlite3.Connection) -> dict[str, tuple[str | None, str | None]]:
    """The stored ETag / Last-Modified per source, for conditional GET."""
    rows = connection.execute(
        "SELECT source_name, etag, last_modified FROM source_state"
    ).fetchall()
    return {row["source_name"]: (row["etag"], row["last_modified"]) for row in rows}


def record_outcomes(
    connection: sqlite3.Connection, outcomes: Iterable[SourceOutcome], *, now: datetime
) -> None:
    """Store per-source state after a run, including the validators for next time."""
    stamp = _stamp(now)
    for outcome in outcomes:
        connection.execute(
            """
            INSERT INTO source_state (source_name, etag, last_modified, last_ok,
                                      last_error, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_name) DO UPDATE SET
                etag          = COALESCE(excluded.etag, source_state.etag),
                last_modified = COALESCE(excluded.last_modified, source_state.last_modified),
                last_ok       = COALESCE(excluded.last_ok, source_state.last_ok),
                last_error    = excluded.last_error,
                last_seen_at  = excluded.last_seen_at
            """,
            (
                outcome.source_name,
                outcome.etag,
                outcome.last_modified,
                stamp if outcome.ok else None,
                outcome.error,
                stamp,
            ),
        )
    connection.commit()


def start_run(connection: sqlite3.Connection, *, now: datetime) -> int:
    cursor = connection.execute("INSERT INTO runs (started_at) VALUES (?)", (_stamp(now),))
    connection.commit()
    return int(cursor.lastrowid or 0)


def finish_run(
    connection: sqlite3.Connection,
    run_id: int,
    *,
    now: datetime,
    counters: Mapping[str, int],
    notes: str = "",
) -> None:
    """Close a run with its real funnel counters. Unknown counter names are rejected."""
    allowed = {"items_seen", "items_new", "clusters", "candidates", "sources_ok", "sources_failed"}
    unknown = set(counters) - allowed
    if unknown:
        raise ValueError(f"unknown run counters: {sorted(unknown)}")
    assignments = ", ".join(f"{name} = ?" for name in counters)
    connection.execute(
        f"UPDATE runs SET finished_at = ?, notes = ?{', ' + assignments if counters else ''} "
        "WHERE id = ?",
        (_stamp(now), notes, *counters.values(), run_id),
    )
    connection.commit()


def latest_run(connection: sqlite3.Connection) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT 1"
    ).fetchone()


def save_digest(
    connection: sqlite3.Connection,
    *,
    digest_date: str,
    generated_at: str,
    payload: str,
    read_seconds: int,
    card_count: int,
    run_id: int | None = None,
) -> None:
    """Store a finished digest, replacing an earlier one for the same day.

    Replacing is correct: a second run on the same day is a re-run, not a second edition.
    """
    connection.execute(
        """
        INSERT INTO digests (digest_date, generated_at, run_id, read_seconds, card_count, payload)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(digest_date) DO UPDATE SET
            generated_at = excluded.generated_at,
            run_id       = excluded.run_id,
            read_seconds = excluded.read_seconds,
            card_count   = excluded.card_count,
            payload      = excluded.payload
        """,
        (digest_date, generated_at, run_id, read_seconds, card_count, payload),
    )
    connection.commit()


def latest_digest(connection: sqlite3.Connection) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM digests ORDER BY digest_date DESC LIMIT 1"
    ).fetchone()


def digest_for(connection: sqlite3.Connection, digest_date: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM digests WHERE digest_date = ?", (digest_date,)
    ).fetchone()


def digest_dates(connection: sqlite3.Connection, limit: int = 60) -> list[str]:
    rows = connection.execute(
        "SELECT digest_date FROM digests ORDER BY digest_date DESC LIMIT ?", (limit,)
    ).fetchall()
    return [row["digest_date"] for row in rows]
