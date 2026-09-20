"""Tests for the honesty validator.

Each test is a specific way a small model lies, and the expectation is always the same: the
run fails rather than showing it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pulse_scout.core.validate import DigestRejected, validate_judgements
from pulse_scout.models import Item, Judgement

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

ITEM = Item.create(
    source_name="FastAPI releases",
    tier=1,
    title="FastAPI 0.120.1 released",
    url="https://example.test/fastapi-0-120-1",
    summary="Adds support for Pydantic 2.12 and drops Python 3.9.",
    published_at=NOW,
)
ITEMS = {"a1": ITEM}


def judgement(**overrides) -> Judgement:
    defaults = {
        "item_id": "a1",
        "headline": "FastAPI 0.120.1 ist da",
        "body": "Die Version unterstützt Pydantic 2.12. Python 3.9 fällt raus.",
        "why_you": "Dein Backend läuft auf FastAPI, der Sprung betrifft dich direkt.",
    }
    return Judgement(**(defaults | overrides))


def check(judgements, thread="Zwei Dinge hängen heute zusammen. Beide betreffen dein Backend."):
    validate_judgements(judgements, thread, items=ITEMS, now=NOW)


def test_a_clean_draft_passes() -> None:
    check([judgement()])


def test_an_invented_item_id_fails_the_run() -> None:
    """The most direct form of fabrication: writing about something that was never fetched."""
    with pytest.raises(DigestRejected, match="never fetched"):
        check([judgement(item_id="a9")])


def test_writing_about_the_same_item_twice_fails() -> None:
    with pytest.raises(DigestRejected, match="same item twice"):
        check([judgement(), judgement()])


def test_an_invented_number_fails_the_run() -> None:
    """A fabricated benchmark figure is the most damaging thing a small model produces here."""
    with pytest.raises(DigestRejected, match=r"\['40'\]"):
        check([judgement(body="Die Version ist 40 Prozent schneller.")])


def test_a_number_from_the_source_passes() -> None:
    check([judgement(body="Pydantic 2.12 wird unterstützt, Python 3.9 nicht mehr.")])


def test_a_shortened_version_number_passes() -> None:
    """The source says 0.120.1; writing 0.120 is a shortening, not an invention."""
    check([judgement(headline="FastAPI 0.120 ist da")])


def test_a_lengthened_version_number_fails() -> None:
    with pytest.raises(DigestRejected, match="0.120.1.7"):
        check([judgement(headline="FastAPI 0.120.1.7 ist da")])


def test_the_current_year_is_context_not_a_claim() -> None:
    check([judgement(body="Seit 2026 läuft das anders. Pydantic 2.12 kommt mit.")])


def test_an_invented_link_fails_the_run() -> None:
    with pytest.raises(DigestRejected, match="contains a link"):
        check([judgement(body="Mehr dazu unter https://example.test/erfunden")])


def test_a_missing_why_you_line_fails() -> None:
    """That sentence is the card; without it the item is just a headline he could get anywhere."""
    with pytest.raises(DigestRejected, match="that is the card"):
        check([judgement(why_you="   ")])


def test_an_empty_headline_or_body_fails() -> None:
    with pytest.raises(DigestRejected, match="no headline"):
        check([judgement(headline="")])
    with pytest.raises(DigestRejected, match="no body"):
        check([judgement(body="")])


def test_an_overlong_body_fails_the_budget() -> None:
    """Five minutes is a hard constraint, not an aspiration."""
    with pytest.raises(DigestRejected, match="over the 420 budget"):
        check([judgement(body="Sehr lang. " * 60)])


def test_no_judgements_at_all_fails() -> None:
    with pytest.raises(DigestRejected, match="no judgements"):
        check([])


def test_an_empty_thread_fails() -> None:
    with pytest.raises(DigestRejected, match="thread is empty"):
        check([judgement()], thread="  ")


def test_an_invented_number_in_the_thread_fails() -> None:
    with pytest.raises(DigestRejected, match="thread contains invented numbers"):
        check([judgement()], thread="Heute gab es 17 wichtige Meldungen.")


def test_the_thread_may_use_numbers_from_any_of_the_items() -> None:
    check([judgement()], thread="Pydantic 2.12 zieht sich durch den Tag. Alles hängt daran.")
