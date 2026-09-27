"""The idempotence check the daily timer relies on: one digest per Berlin day, never two."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pulse_scout.pipeline import digest_already_built
from pulse_scout.store import repo
from pulse_scout.store.db import connect


def store(path: Path, day: str) -> None:
    connection = connect(path)
    repo.save_digest(
        connection,
        digest_date=day,
        generated_at=f"{day}T20:40:00+02:00",
        payload="{}",
        read_seconds=0,
        card_count=0,
    )
    connection.close()


def test_nothing_built_yet_means_build(tmp_path: Path) -> None:
    connection = connect(tmp_path / "pulse.db")
    assert not digest_already_built(connection, now=datetime(2026, 9, 27, 18, 30, tzinfo=UTC))


def test_todays_digest_means_skip(tmp_path: Path) -> None:
    store(tmp_path / "pulse.db", "2026-09-27")
    connection = connect(tmp_path / "pulse.db")
    assert digest_already_built(connection, now=datetime(2026, 9, 27, 18, 30, tzinfo=UTC))


def test_yesterdays_digest_means_build(tmp_path: Path) -> None:
    """The morning catch-up after a missed evening builds today's."""
    store(tmp_path / "pulse.db", "2026-09-26")
    connection = connect(tmp_path / "pulse.db")
    assert not digest_already_built(connection, now=datetime(2026, 9, 27, 5, 0, tzinfo=UTC))


def test_the_day_is_berlins_not_utcs(tmp_path: Path) -> None:
    """22:30 UTC on the 27th is already the 28th in Berlin."""
    store(tmp_path / "pulse.db", "2026-09-27")
    connection = connect(tmp_path / "pulse.db")
    assert not digest_already_built(connection, now=datetime(2026, 9, 27, 22, 30, tzinfo=UTC))
