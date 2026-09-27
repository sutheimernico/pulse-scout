"""Tests for the faithfulness guard — the pure half and the model pass on a fake.

The case that motivated it is replayed here with synthetic text: a source that says a thing
was *slowed*, and a draft that says it was *stopped*. The fake checker answers the way a
working checker should; what is under test is what the digest does with that answer.
"""

from __future__ import annotations

import pytest

from pulse_scout.core.faithfulness import (
    CardCheck,
    Verdict,
    apply_check,
    assemble,
    score_labels,
    source_sentence,
    split_sentences,
)
from pulse_scout.core.validate import MAX_HEADLINE_CHARS
from pulse_scout.llm.ollama import OllamaError
from pulse_scout.llm.prompts import VERIFY_SYSTEM
from pulse_scout.llm.verifier import guard, parse_verdict, source_view
from pulse_scout.llm.writer import SUMMARY_BUDGET, WriterError
from pulse_scout.models import Item, Judgement
from tests.fakes import FakeClient

ITEM = Item.create(
    source_name="Feed",
    tier=3,
    title="Four labs agree to slow model releases",
    url="https://example.test/slow",
    summary="Four labs agreed to slow model releases for safety reasons. A lawsuit followed.",
)

DRAFT = Judgement(
    item_id="a1",
    headline="Vier Labore bremsen ihre Releases",
    body="Vier Labore haben vereinbart, Releases einzustellen. Darauf folgte eine Klage.",
    why_you="Betrifft die Modelle, die du nutzt.",
)


def yes(sentence: str) -> Verdict:
    return Verdict(sentence=sentence, supported=True, answer="YES")


def no(sentence: str) -> Verdict:
    return Verdict(sentence=sentence, supported=False, answer="NO")


# --- splitting --------------------------------------------------------------------------------


def test_prose_splits_into_sentences() -> None:
    assert split_sentences("Erster Satz. Zweiter Satz! Dritter?") == [
        "Erster Satz.",
        "Zweiter Satz!",
        "Dritter?",
    ]


def test_abbreviations_and_versions_do_not_split() -> None:
    text = "Das betrifft z. B. die Version 2.3 von Qwen3.8. Danach kommt mehr."
    assert split_sentences(text) == [
        "Das betrifft z. B. die Version 2.3 von Qwen3.8.",
        "Danach kommt mehr.",
    ]


def test_empty_prose_has_no_sentences() -> None:
    assert split_sentences("   ") == []


# --- verdict parsing --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("YES", True),
        ("yes.", True),
        ("Ja", True),
        ("NO", False),
        (" no, the source says slow", False),
        ("Nein.", False),
        ("Maybe", None),
        ("", None),
        ("42", None),
    ],
)
def test_verdicts_are_parsed_strictly(answer: str, expected: bool | None) -> None:
    assert parse_verdict(answer) is expected


def test_an_unreadable_verdict_is_not_a_yes() -> None:
    assert Verdict(sentence="x", supported=None).keep is False


# --- what a card looks like afterwards --------------------------------------------------------


def test_an_unsupported_sentence_is_dropped_and_the_rest_is_kept() -> None:
    sentences = split_sentences(DRAFT.body)
    check = CardCheck(headline=yes(DRAFT.headline), body=(no(sentences[0]), yes(sentences[1])))
    fixed, quoted = apply_check(DRAFT, ITEM, check)
    assert fixed.body == "Darauf folgte eine Klage."
    assert fixed.headline == DRAFT.headline
    assert fixed.why_you == DRAFT.why_you
    assert quoted is False


def test_a_body_with_nothing_left_becomes_the_sources_own_first_sentence() -> None:
    sentences = split_sentences(DRAFT.body)
    check = CardCheck(headline=yes(DRAFT.headline), body=tuple(no(s) for s in sentences))
    fixed, quoted = apply_check(DRAFT, ITEM, check)
    assert fixed.body == "Four labs agreed to slow model releases for safety reasons."
    assert quoted is True


def test_a_rejected_headline_becomes_the_source_title() -> None:
    check = CardCheck(headline=no(DRAFT.headline), body=(yes("Darauf folgte eine Klage."),))
    fixed, _ = apply_check(DRAFT, ITEM, check)
    assert fixed.headline == ITEM.title


def test_a_long_source_title_is_clipped_to_the_headline_budget() -> None:
    long_item = Item.create(source_name="Feed", tier=3, title="word " * 60, summary="")
    check = CardCheck(headline=no("x"), body=())
    fixed, quoted = apply_check(DRAFT, long_item, check)
    assert len(fixed.headline) <= MAX_HEADLINE_CHARS
    assert fixed.headline.endswith("…")
    assert quoted is True


def test_without_a_summary_the_fallback_is_the_title() -> None:
    bare = Item.create(source_name="Feed", tier=3, title="Only a title", summary="")
    assert source_sentence(bare) == "Only a title"


def test_the_report_counts_and_tells_the_reader() -> None:
    sentences = split_sentences(DRAFT.body)
    checks = {
        "a1": CardCheck(
            headline=yes(DRAFT.headline),
            body=(no(sentences[0]), Verdict(sentence=sentences[1], supported=None)),
        )
    }
    report = assemble([DRAFT], {"a1": ITEM}, checks, seconds=1.5, model="m")
    assert (report.checked, report.rejected, report.unreadable) == (3, 2, 1)
    assert report.quoted == frozenset({"a1"})
    note = report.note()
    assert note is not None
    assert "2 von 3 Sätze verworfen" in note
    assert "Originaltext" in note


def test_a_clean_report_says_nothing() -> None:
    checks = {"a1": CardCheck(headline=yes("h"), body=(yes("b"),))}
    report = assemble([DRAFT], {"a1": ITEM}, checks, seconds=0.1, model="m")
    assert report.rejected == 0
    assert report.note() is None


# --- the model pass, on a fake ----------------------------------------------------------------


def test_the_guard_asks_once_per_headline_and_body_sentence() -> None:
    client = FakeClient(replies=["YES", "NO", "YES"])
    report = guard([DRAFT], {"a1": ITEM}, client=client)
    assert len(client.calls) == 3
    assert report.judgements[0].body == "Darauf folgte eine Klage."
    assert report.rejected == 1


def test_the_checker_sees_the_source_before_the_sentence_and_a_constant_system_block() -> None:
    client = FakeClient(replies=["YES", "YES", "YES"])
    guard([DRAFT], {"a1": ITEM}, client=client)
    assert {call["system"] for call in client.calls} == {VERIFY_SYSTEM}
    first = client.calls[0]["prompt"]
    assert first.index(ITEM.title) < first.index(DRAFT.headline)
    # Consecutive checks of one item share everything up to the sentence: that is what the
    # prefix cache needs.
    prefix = first.split("Sentence:")[0]
    assert all(call["prompt"].startswith(prefix) for call in client.calls)


def test_the_checker_sees_only_what_the_writer_saw() -> None:
    long_item = Item.create(
        source_name="Feed", tier=3, title="T", summary="a" * SUMMARY_BUDGET + "SECRET"
    )
    assert "SECRET" not in source_view(long_item)


def test_the_answer_is_capped_to_a_few_tokens() -> None:
    client = FakeClient(replies=["YES", "YES", "YES"])
    guard([DRAFT], {"a1": ITEM}, client=client)
    assert all(call["options"]["num_predict"] <= 5 for call in client.calls)


def test_an_unreachable_checker_fails_the_run() -> None:
    client = FakeClient(fail_with=OllamaError("connection refused"))
    with pytest.raises(WriterError):
        guard([DRAFT], {"a1": ITEM}, client=client)


# --- scoring against labels -------------------------------------------------------------------


def test_catch_rate_and_false_alarms_are_counted_separately() -> None:
    labels = [True, True, False, False, False]
    kept = [True, False, False, True, False]
    result = score_labels(labels, kept)
    assert result["caught"] == 2
    assert result["missed"] == 1
    assert result["false_alarms"] == 1
    assert result["catch_rate"] == pytest.approx(0.667)
    assert result["false_alarm_rate"] == pytest.approx(0.5)


def test_mismatched_lengths_are_refused() -> None:
    with pytest.raises(ValueError):
        score_labels([True], [True, False])
