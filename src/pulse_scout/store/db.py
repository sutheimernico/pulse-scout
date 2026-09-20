"""The database: schema, migrations, connections.

Migrations run off `PRAGMA user_version`, which is a plain integer SQLite keeps in the file
header. No migration framework, no dependency, and the whole history is visible as a list of
SQL steps in one place.

The schema starts small on purpose. Digest tables arrive with phase 2 as version 2 — writing
them now would mean shipping empty tables whose shape is a guess, and it would mean the
migration mechanism is never exercised before it matters.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / "data" / "pulse.db"

SCHEMA_VERSION = 1

_MIGRATIONS: Sequence[tuple[int, str]] = (
    (
        1,
        """
        -- Every item we have ever seen. This table is what makes the funnel possible:
        -- most configured sources are snapshots (the Azure feed returns its newest 200
        -- entries every call, HuggingFace the same 50 models), so without a record of what
        -- has already been through the pipeline, every day would re-process everything.
        CREATE TABLE items (
            item_key     TEXT PRIMARY KEY,
            source_name  TEXT NOT NULL,
            tier         INTEGER NOT NULL,
            title        TEXT NOT NULL,
            url          TEXT,
            summary      TEXT NOT NULL DEFAULT '',
            published_at TEXT,
            engagement   TEXT NOT NULL DEFAULT '{}',
            raw_id       TEXT,
            first_seen   TEXT NOT NULL,
            last_seen    TEXT NOT NULL
        );
        CREATE INDEX items_first_seen ON items (first_seen);
        CREATE INDEX items_source ON items (source_name);

        -- HTTP validators, so tomorrow's run can ask "changed?" instead of downloading
        -- 150 kB of unchanged feed. Kept here rather than next to the cached bodies so
        -- there is exactly one place where per-source state lives.
        CREATE TABLE source_state (
            source_name   TEXT PRIMARY KEY,
            etag          TEXT,
            last_modified TEXT,
            last_ok       TEXT,
            last_error    TEXT,
            last_seen_at  TEXT NOT NULL
        );

        -- One row per pipeline run, with the funnel counters the screen promises are real.
        CREATE TABLE runs (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at     TEXT NOT NULL,
            finished_at    TEXT,
            items_seen     INTEGER NOT NULL DEFAULT 0,
            items_new      INTEGER NOT NULL DEFAULT 0,
            clusters       INTEGER NOT NULL DEFAULT 0,
            candidates     INTEGER NOT NULL DEFAULT 0,
            sources_ok     INTEGER NOT NULL DEFAULT 0,
            sources_failed INTEGER NOT NULL DEFAULT 0,
            notes          TEXT NOT NULL DEFAULT ''
        );
        """,
    ),
)


def migrate(connection: sqlite3.Connection) -> int:
    """Bring a connection up to the current schema. Safe to call on every open."""
    current = connection.execute("PRAGMA user_version").fetchone()[0]
    for version, statements in _MIGRATIONS:
        if version <= current:
            continue
        connection.executescript(statements)
        connection.execute(f"PRAGMA user_version = {version}")
        current = version
    connection.commit()
    return current


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the database, creating and migrating it if necessary."""
    path = path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    # Foreign keys are off by default in SQLite, which surprises everyone exactly once.
    connection.execute("PRAGMA foreign_keys = ON")
    # A daily batch job plus a read-only API: WAL keeps the API readable during a run.
    connection.execute("PRAGMA journal_mode = WAL")
    migrate(connection)
    return connection
