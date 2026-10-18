"""The observation row reports what the build stored, and leaves the verdict to Nico."""

from __future__ import annotations

from datetime import date

from pulse_scout.core.observation import HEADER, SEPARATOR, missing_days, row

FULL = {
    "digest_date": "2026-09-28",
    "generated_at": "2026-09-28T20:41:07+02:00",
    "cards": [{}, {}, {}],
    "counters": {"items_seen": 594, "items_new": 180, "candidates": 40, "sources_failed": 1},
    "read_seconds": 214,
    "guard": {"checked": 14, "rejected": 3, "quoted_cards": 1},
    "stats": {
        "total_seconds": 725.4,
        "scoring": {"parse_failures": 2, "rank_correlation": 0.3871},
    },
}


def test_a_full_record_fills_every_machine_column() -> None:
    cells = [cell.strip() for cell in row(FULL).strip("|").split("|")]
    assert cells == [
        "2026-09-28", "20:41", "594", "180", "40", "3", "3:34", "12:05",
        "2", "0.39", "3/14", "1", "1", "",
    ]


def test_the_verdict_is_left_empty() -> None:
    assert row(FULL).endswith("|  |")


def test_an_old_record_says_what_it_lacks_instead_of_guessing() -> None:
    old = {"digest_date": "2026-09-20", "generated_at": "2026-09-20T16:55:00+02:00",
           "cards": [{}], "counters": {"items_seen": 396}, "read_seconds": 16}
    cells = [cell.strip() for cell in row(old).strip("|").split("|")]
    assert cells[7] == "–"
    assert cells[10] == "vor dem Check"


def test_a_skipped_scoring_pass_is_named() -> None:
    skipped = {**FULL, "stats": {"scoring": {"skipped": True}}}
    assert "übersprungen" in row(skipped)


def test_header_and_separator_have_the_same_width() -> None:
    assert HEADER.count("|") == SEPARATOR.count("|") == row(FULL).count("|")


def test_missing_days_names_every_gap_up_to_today() -> None:
    gaps = missing_days(["2026-10-09", "2026-10-10", "2026-10-12"], today=date(2026, 10, 13))
    assert gaps == ["2026-10-11", "2026-10-13"]


def test_missing_days_is_empty_without_any_digest() -> None:
    assert missing_days([], today=date(2026, 10, 13)) == []
