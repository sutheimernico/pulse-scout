"""Tests for digest assembly, read time and persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from pulse_scout.core.dedupe import Cluster
from pulse_scout.core.digest import (
    READ_BUDGET_SECONDS,
    Card,
    KuerLine,
    build,
    local_date,
    read_seconds,
    render_markdown,
)
from pulse_scout.core.ranking import Candidate
from pulse_scout.core.selection import select
from pulse_scout.llm.scorer import ScoredCandidate
from pulse_scout.llm.writer import Draft
from pulse_scout.models import Item, Judgement
from pulse_scout.pipeline import FunnelCounters
from pulse_scout.store.db import connect
from pulse_scout.store.repo import digest_dates, digest_for, latest_digest, save_digest
from tests.fakes import slug

NOW = datetime(2026, 9, 20, 21, 30, tzinfo=UTC)
COUNTERS = FunnelCounters(
    items_seen=570, items_new=84, clusters=80, candidates=40, sources_ok=60, sources_failed=0
)


def entry(title: str, *, tier: int = 1, rank: int = 1, model_score: int | None = 8):
    item = Item.create(
        source_name="Feed",
        tier=tier,
        title=title,
        url=f"https://example.test/{slug(title)}",
        summary="Kontext.",
        published_at=NOW,
    )
    return ScoredCandidate(
        candidate=Candidate(cluster=Cluster(members=(item,)), score=1.0),
        deterministic_rank=rank,
        model_score=model_score,
        model_rank=rank,
    )


def draft_for(entries, *, thread="Alles hängt zusammen. Mehr nicht.", truncated=False) -> Draft:
    items = {f"a{i}": e.candidate.cluster.primary for i, e in enumerate(entries, start=1)}
    judgements = [
        Judgement(
            item_id=handle,
            headline=f"Schlagzeile zu {item.title}",
            body="Zwei Saetze Inhalt. Wirklich zwei.",
            why_you="Betrifft dein Backend.",
        )
        for handle, item in items.items()
    ]
    return Draft(judgements=judgements, thread=thread, items=items, truncated=truncated)


def test_the_digest_is_dated_by_the_local_day_it_was_produced_on() -> None:
    """An evening run in Berlin is still that evening, not the next morning."""
    assert local_date(datetime(2026, 9, 20, 21, 30, tzinfo=UTC)).isoformat() == "2026-09-20"
    # 23:30 UTC is already the next day in Berlin, and the digest must say so.
    assert local_date(datetime(2026, 9, 20, 23, 30, tzinfo=UTC)).isoformat() == "2026-09-21"


def test_every_card_traces_back_to_a_real_item() -> None:
    entries = [entry(f"Story {i}", tier=1 + i % 3, rank=i) for i in range(1, 4)]
    digest = build(
        selection=select(entries), draft=draft_for(entries), counters=COUNTERS, now=NOW
    )
    keys = {e.candidate.cluster.primary.key for e in entries}
    assert {card.item_key for card in digest.cards} <= keys
    assert all(card.url for card in digest.cards)


def test_a_slot_the_writer_skipped_is_left_empty_not_filled() -> None:
    entries = [entry(f"Story {i}", tier=1 + i % 3, rank=i) for i in range(1, 4)]
    draft = draft_for(entries)
    thin = Draft(judgements=draft.judgements[:1], thread=draft.thread, items=draft.items)

    digest = build(selection=select(entries), draft=thin, counters=COUNTERS, now=NOW)

    assert len(digest.cards) == 1


def test_the_funnel_line_shows_the_real_numbers() -> None:
    entries = [entry("Story one")]
    digest = build(
        selection=select(entries), draft=draft_for(entries), counters=COUNTERS, now=NOW
    )
    assert digest.funnel_line == "570 gesichtet → 1 für dich"
    assert digest.counters["items_seen"] == 570


def test_read_time_counts_prose_and_kuer_lines() -> None:
    cards = [Card("h", " ".join(["wort"] * 200), "w", None, "S", 1, "k")]
    assert read_seconds(cards, "", []) == pytest.approx(61, abs=2)
    kuer = [KuerLine("t", None, "S", 3)] * 10
    assert read_seconds([], "", kuer) == 30


def test_going_over_the_five_minute_budget_is_said_out_loud() -> None:
    """C5 is a constraint, not an aspiration; an unchecked estimate is the same as none."""
    entries = [entry(f"Story {i}", tier=1 + i % 3, rank=i) for i in range(1, 6)]
    draft = draft_for(entries)
    long_draft = Draft(
        judgements=[
            Judgement(j.item_id, j.headline, " ".join(["wort"] * 400), j.why_you)
            for j in draft.judgements
        ],
        thread=draft.thread,
        items=draft.items,
    )

    digest = build(selection=select(entries), draft=long_draft, counters=COUNTERS, now=NOW)

    assert digest.over_budget is True
    assert digest.read_seconds > READ_BUDGET_SECONDS
    assert any("Budget" in note for note in digest.notes)


def test_a_quiet_day_says_so() -> None:
    entries = [entry("A good one", model_score=9), entry("Filler", model_score=1, rank=2)]
    digest = build(
        selection=select(entries), draft=draft_for(entries), counters=COUNTERS, now=NOW
    )
    assert any("Ruhiger Tag" in note for note in digest.notes)


def test_truncation_is_visible_to_the_reader() -> None:
    entries = [entry("Story one")]
    digest = build(
        selection=select(entries),
        draft=draft_for(entries, truncated=True),
        counters=COUNTERS,
        now=NOW,
    )
    assert any("abgeschnitten" in note for note in digest.notes)


def test_markdown_contains_every_section_it_should() -> None:
    entries = [entry(f"Story {i}", tier=1 + i % 3, rank=i) for i in range(1, 9)]
    digest = build(
        selection=select(entries), draft=draft_for(entries), counters=COUNTERS, now=NOW
    )
    text = render_markdown(digest)

    assert "# pulse-scout — 2026-09-20" in text
    assert "570 gesichtet" in text
    assert "## Heute" in text
    assert "**Darum geht's dich an:**" in text
    assert "## Roter Faden" in text
    assert "## Kür" in text
    assert "Dein Stack" in text


def test_markdown_for_an_empty_day_says_nothing_happened() -> None:
    entries = [entry("Filler", model_score=0)]
    digest = build(
        selection=select(entries), draft=draft_for(entries), counters=COUNTERS, now=NOW
    )
    assert "Heute hat nichts einen Platz verdient" in render_markdown(digest)


def test_the_digest_round_trips_through_json() -> None:
    entries = [entry("Story one")]
    digest = build(
        selection=select(entries), draft=draft_for(entries), counters=COUNTERS, now=NOW
    )
    payload = json.loads(digest.to_json())
    assert payload["digest_date"] == "2026-09-20"
    assert payload["cards"][0]["why_you"]


def test_a_digest_is_stored_and_read_back(tmp_path) -> None:
    connection = connect(tmp_path / "pulse.db")
    entries = [entry("Story one")]
    digest = build(
        selection=select(entries), draft=draft_for(entries), counters=COUNTERS, now=NOW
    )

    save_digest(
        connection,
        digest_date=digest.digest_date,
        generated_at=digest.generated_at,
        payload=digest.to_json(),
        read_seconds=digest.read_seconds,
        card_count=len(digest.cards),
        run_id=1,
    )

    assert latest_digest(connection)["digest_date"] == "2026-09-20"
    assert digest_for(connection, "2026-09-20")["card_count"] == 1
    assert digest_for(connection, "2026-09-19") is None
    assert digest_dates(connection) == ["2026-09-20"]
    connection.close()


def test_re_running_the_same_day_replaces_rather_than_duplicates(tmp_path) -> None:
    connection = connect(tmp_path / "pulse.db")
    for count in (1, 3):
        save_digest(
            connection,
            digest_date="2026-09-20",
            generated_at="2026-09-20T21:30:00+02:00",
            payload="{}",
            read_seconds=100,
            card_count=count,
        )
    assert digest_dates(connection) == ["2026-09-20"]
    assert digest_for(connection, "2026-09-20")["card_count"] == 3
    connection.close()


def test_the_guarded_judgements_replace_the_writers_and_the_reader_is_told() -> None:
    from pulse_scout.core.faithfulness import CardCheck, Verdict, assemble

    entries = [entry("Story one"), entry("Story two", tier=2, rank=2)]
    draft = draft_for(entries)
    rejected = CardCheck(
        headline=Verdict(sentence="h", supported=True),
        body=(
            Verdict(sentence="Zwei Saetze Inhalt.", supported=False),
            Verdict(sentence="Wirklich zwei.", supported=False),
        ),
    )
    held = CardCheck(
        headline=Verdict(sentence="h", supported=True),
        body=(
            Verdict(sentence="Zwei Saetze Inhalt.", supported=True),
            Verdict(sentence="Wirklich zwei.", supported=False),
        ),
    )
    guard = assemble(
        draft.judgements, draft.items, {"a1": rejected, "a2": held}, seconds=2.0, model="m"
    )

    digest = build(
        selection=select(entries), draft=draft, counters=COUNTERS, now=NOW, guard=guard
    )

    by_title = {card.item_key: card for card in digest.cards}
    first = by_title[entries[0].candidate.cluster.primary.key]
    second = by_title[entries[1].candidate.cluster.primary.key]
    assert first.quoted is True
    assert first.body == "Kontext."
    assert second.quoted is False
    assert second.body == "Zwei Saetze Inhalt."
    assert any(note.startswith("Faktencheck: 3 von 6") for note in digest.notes)
    assert digest.guard["rejected"] == 3
    assert "_Originaltext der Quelle:_ Kontext." in render_markdown(digest)


def test_a_digest_without_a_guard_has_no_guard_record() -> None:
    entries = [entry("Story one")]
    digest = build(
        selection=select(entries), draft=draft_for(entries), counters=COUNTERS, now=NOW
    )
    assert digest.guard == {}
    assert all(card.quoted is False for card in digest.cards)


def test_run_stats_travel_with_the_digest() -> None:
    entries = [entry("Story one")]
    stats = {"total_seconds": 612.3, "scoring": {"rank_correlation": 0.41}}
    digest = build(
        selection=select(entries), draft=draft_for(entries), counters=COUNTERS, now=NOW,
        stats=stats,
    )
    assert json.loads(digest.to_json())["stats"] == stats
