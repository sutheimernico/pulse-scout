"""Tests for the writing pass.

Three of these script a model that lies in a different way each time. All three must end with
the run failing, because the alternative — a plausible digest built on an invention — is the
one outcome this project cannot ship.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from pulse_scout.core.dedupe import Cluster
from pulse_scout.core.ranking import Candidate
from pulse_scout.core.validate import DigestRejected
from pulse_scout.llm.ollama import OllamaError
from pulse_scout.llm.scorer import ScoredCandidate
from pulse_scout.llm.writer import (
    Draft,
    WriterError,
    extract_json,
    render_items,
    short_ids,
    write_digest,
)
from pulse_scout.models import Item
from tests.fakes import FakeClient, slug

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def finalist(title: str, summary: str = "Ein Satz Kontext.", tier: int = 1) -> ScoredCandidate:
    item = Item.create(
        source_name="Feed",
        tier=tier,
        title=title,
        url=f"https://example.test/{slug(title)}",
        summary=summary,
        published_at=NOW,
    )
    return ScoredCandidate(
        candidate=Candidate(cluster=Cluster(members=(item,)), score=1.0),
        deterministic_rank=1,
    )


FINALISTS = [
    finalist("FastAPI 0.120 released", "Adds Pydantic 2.12 support."),
    finalist("Azure Container Apps adds GPU support", "Now generally available."),
]

GOOD = json.dumps(
    {
        "judgements": [
            {
                "item_id": "a1",
                "headline": "FastAPI 0.120 ist da",
                "body": "Die Version bringt Pydantic 2.12. Mehr steht nicht drin.",
                "why_you": "Dein Backend läuft darauf.",
            }
        ],
        "thread": "Beides betrifft dein Backend. Mehr passiert heute nicht.",
    }
)


def run(reply: str, **kwargs) -> Draft:
    return write_digest(FINALISTS, client=FakeClient(replies=[reply]), now=NOW, **kwargs)


def test_a_clean_answer_becomes_a_draft() -> None:
    draft = run(GOOD)
    assert len(draft.judgements) == 1
    assert draft.judgements[0].item_id == "a1"
    assert draft.attempts == 1
    assert set(draft.items) == {"a1", "a2"}


def test_items_are_given_short_ids_not_urls() -> None:
    """Fewer tokens, and 'did the model invent this?' becomes an exact lookup."""
    handles = short_ids(FINALISTS)
    assert list(handles) == ["a1", "a2"]
    rendered = render_items(handles)
    assert "[a1] FastAPI 0.120 released (Feed)" in rendered
    assert "http" not in rendered


def test_a_hallucinated_item_id_fails_the_run() -> None:
    reply = GOOD.replace('"a1"', '"a7"')
    with pytest.raises(DigestRejected, match="never fetched"):
        run(reply, max_attempts=1)


def test_an_invented_number_fails_the_run() -> None:
    reply = GOOD.replace("Mehr steht nicht drin.", "Sie ist 60 Prozent schneller.")
    with pytest.raises(DigestRejected, match=r"\['60'\]"):
        run(reply, max_attempts=1)


def test_prose_instead_of_json_fails_the_run() -> None:
    with pytest.raises(DigestRejected, match="no JSON object"):
        run("Guten Morgen! Hier ist dein Digest für heute.", max_attempts=1)


def test_a_fenced_answer_is_still_read() -> None:
    """Small models wrap JSON in markdown fences no matter what the prompt says."""
    draft = run(f"```json\n{GOOD}\n```")
    assert len(draft.judgements) == 1


def test_a_second_attempt_is_made_before_giving_up() -> None:
    client = FakeClient(replies=["not json at all", GOOD])
    draft = write_digest(FINALISTS, client=client, now=NOW, max_attempts=2)
    assert draft.attempts == 2
    assert len(client.calls) == 2


def test_two_failures_end_the_run() -> None:
    client = FakeClient(replies=["nope", "still nope"])
    with pytest.raises(DigestRejected, match="failed 2 times"):
        write_digest(FINALISTS, client=client, now=NOW, max_attempts=2)


def test_an_unreachable_model_is_a_writer_error_not_a_rejection() -> None:
    """A dead Ollama is an operational problem, not the model lying. They read differently."""
    client = FakeClient(fail_with=OllamaError("cannot reach Ollama"))
    with pytest.raises(WriterError, match="cannot reach Ollama"):
        write_digest(FINALISTS, client=client, now=NOW)


def test_writing_with_no_finalists_is_refused() -> None:
    with pytest.raises(WriterError, match="no finalists"):
        write_digest([], client=FakeClient(), now=NOW)


def test_the_output_cap_and_context_are_set_explicitly() -> None:
    client = FakeClient(replies=[GOOD])
    write_digest(FINALISTS, client=client, now=NOW, output_cap=500)
    options = client.calls[0]["options"]
    assert options["num_predict"] == 500
    assert options["num_ctx"] >= 8192


def test_truncation_is_reported() -> None:
    client = FakeClient(replies=[GOOD], done_reason="length")
    draft = write_digest(FINALISTS, client=client, now=NOW)
    assert draft.truncated is True


@pytest.mark.parametrize(
    "payload",
    ['{"thread": "x"}', '{"judgements": "not a list"}', '{"judgements": ["a string"]}'],
)
def test_malformed_shapes_are_refused(payload: str) -> None:
    with pytest.raises((WriterError, DigestRejected)):
        run(payload, max_attempts=1)


def test_extract_json_finds_an_object_surrounded_by_chatter() -> None:
    assert extract_json('Sure!\n{"a": 1}\nHope that helps.') == {"a": 1}


def test_an_id_copied_with_its_brackets_still_resolves() -> None:
    """The prompt shows "[a1]"; with twelve items qwen2.5:7b echoed the brackets (2026-09-27)."""
    draft = run(GOOD.replace('"a1"', '"[a1]"'))
    assert draft.judgements[0].item_id == "a1"
