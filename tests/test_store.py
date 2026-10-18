"""Tests for the SQLite store.

`test_the_same_item_twice_is_new_only_once` is the one that carries the design: without it
the funnel would re-process the Azure feed's 200 entries every single morning.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from pulse_scout.models import Item, SourceOutcome
from pulse_scout.store.db import SCHEMA_VERSION, connect, migrate
from pulse_scout.store.repo import (
    count_items,
    finish_run,
    forget_items_first_seen_at,
    latest_run,
    record_outcomes,
    record_seen,
    start_run,
    validators,
)

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


@pytest.fixture
def db(tmp_path):
    connection = connect(tmp_path / "pulse.db")
    yield connection
    connection.close()


def item(title: str, *, url: str | None = None, src: str = "S") -> Item:
    return Item.create(
        source_name=src,
        tier=1,
        title=title,
        url=url or f"https://example.test/{title.replace(' ', '-')}",
        summary="A summary.",
        published_at=NOW,
        engagement={"points": 10.0},
    )


def test_a_fresh_database_is_at_the_current_schema_version(tmp_path) -> None:
    connection = connect(tmp_path / "new.db")
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_migrating_twice_changes_nothing(tmp_path) -> None:
    connection = connect(tmp_path / "new.db")
    record_seen(connection, [item("A story")], now=NOW)
    assert migrate(connection) == SCHEMA_VERSION
    assert count_items(connection) == 1


def test_the_same_item_twice_is_new_only_once(db) -> None:
    """Most sources are snapshots. This is what stops the funnel becoming a treadmill."""
    first = record_seen(db, [item("A story")], now=NOW)
    second = record_seen(db, [item("A story")], now=NOW + timedelta(days=1))

    assert len(first) == 1
    assert second == []
    assert count_items(db) == 1


def test_last_seen_is_bumped_but_first_seen_is_not(db) -> None:
    record_seen(db, [item("A story")], now=NOW)
    later = NOW + timedelta(days=1)
    record_seen(db, [item("A story")], now=later)

    row = db.execute("SELECT first_seen, last_seen FROM items").fetchone()
    assert row["first_seen"] == NOW.isoformat(timespec="seconds")
    assert row["last_seen"] == later.isoformat(timespec="seconds")


def test_duplicates_inside_one_batch_count_once(db) -> None:
    """Hacker News and a site's own feed can deliver the same canonical URL in one run."""
    url = "https://example.test/one-article"
    fresh = record_seen(
        db,
        [item("Headline from HN", url=url + "?utm_source=hn", src="HN"),
         item("Headline from the blog", url=url, src="Blog")],
        now=NOW,
    )
    assert len(fresh) == 1
    assert count_items(db) == 1


def test_different_items_are_all_new(db) -> None:
    fresh = record_seen(db, [item("One"), item("Two"), item("Three")], now=NOW)
    assert len(fresh) == 3


def test_engagement_survives_a_round_trip(db) -> None:
    record_seen(db, [item("A story")], now=NOW)
    stored = db.execute("SELECT engagement FROM items").fetchone()["engagement"]
    assert stored == '{"points": 10.0}'


def test_validators_start_empty_and_are_remembered(db) -> None:
    assert validators(db) == {}

    record_outcomes(
        db,
        [SourceOutcome(source_name="Azure", ok=True, etag='"v1"', last_modified="Sat, 19 Sep")],
        now=NOW,
    )
    assert validators(db) == {"Azure": ('"v1"', "Sat, 19 Sep")}


def test_a_304_does_not_erase_the_stored_validator(db) -> None:
    """A 304 carries no new ETag; losing the old one would re-download everything tomorrow."""
    record_outcomes(db, [SourceOutcome("Azure", ok=True, etag='"v1"')], now=NOW)
    record_outcomes(
        db, [SourceOutcome("Azure", ok=True, unchanged=True, etag=None)], now=NOW
    )
    assert validators(db)["Azure"][0] == '"v1"'


def test_a_failure_is_recorded_without_losing_the_last_success(db) -> None:
    record_outcomes(db, [SourceOutcome("Feed", ok=True, etag='"v1"')], now=NOW)
    record_outcomes(
        db, [SourceOutcome("Feed", ok=False, error="HTTP 503")], now=NOW + timedelta(days=1)
    )
    row = db.execute("SELECT * FROM source_state WHERE source_name = 'Feed'").fetchone()
    assert row["last_error"] == "HTTP 503"
    assert row["last_ok"] == NOW.isoformat(timespec="seconds")


def test_a_run_records_its_funnel_counters(db) -> None:
    run_id = start_run(db, now=NOW)
    finish_run(
        db,
        run_id,
        now=NOW + timedelta(minutes=8),
        counters={"items_seen": 569, "items_new": 84, "clusters": 80, "candidates": 40},
    )
    row = latest_run(db)
    assert row["items_seen"] == 569
    assert row["items_new"] == 84
    assert row["finished_at"] is not None


def test_an_unknown_counter_is_refused(db) -> None:
    """Counters are shown on screen as real numbers; a typo must not become a silent zero."""
    run_id = start_run(db, now=NOW)
    with pytest.raises(ValueError, match="unknown run counters"):
        finish_run(db, run_id, now=NOW, counters={"itmes_seen": 1})


def test_latest_run_is_none_on_an_empty_database(db) -> None:
    assert latest_run(db) is None


def test_forgetting_a_run_removes_only_its_own_new_items(db) -> None:
    """A run that wrote no digest gives its items back, so the next attempt sees them again."""
    record_seen(db, [item("Old story")], now=NOW - timedelta(days=1))
    record_seen(db, [item("Old story"), item("New story")], now=NOW)

    assert forget_items_first_seen_at(db, now=NOW) == 1

    assert count_items(db) == 1
    again = record_seen(db, [item("New story")], now=NOW + timedelta(hours=1))
    assert [i.title for i in again] == ["New story"]
