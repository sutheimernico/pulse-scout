"""The second pass: ask the model whether the source supports each sentence the writer wrote.

One short call per sentence, answered with a single word. The checker sees only the source as
the writer saw it and the one sentence under test — not the writer's other output, not the
reader profile — so it has nothing to be persuaded by.

Cost is kept small by the prompt's shape: the system block is constant and the source comes
before the sentence, so the second and third sentence about the same item share their whole
prefix with the first and Ollama only reads the few new tokens. The answer is capped at a
handful of tokens, which matters on a CPU that writes at ~4,5 tokens per second.

An answer that is neither yes nor no counts as no. A model that cannot be reached fails the
run, like the writing pass does — an unchecked digest is not a digest we ship.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping, Sequence

from pulse_scout.core.faithfulness import CardCheck, GuardReport, Verdict, assemble, split_sentences
from pulse_scout.llm.ollama import Client, OllamaError
from pulse_scout.llm.prompts import VERIFY_SYSTEM, verify_prompt
from pulse_scout.llm.writer import SUMMARY_BUDGET, WriterError
from pulse_scout.models import Item, Judgement

DEFAULT_VERIFY_MODEL = "qwen2.5:7b"

_OPTIONS = {"num_predict": 3, "temperature": 0.0, "num_ctx": 2048}
_ANSWER = re.compile(r"[A-Za-zÄÖÜäöü]+")
_YES = {"yes", "ja"}
_NO = {"no", "nein"}


def source_view(item: Item) -> str:
    """Exactly what the writer was shown about this item — no more, so no more can be allowed."""
    summary = item.summary[:SUMMARY_BUDGET].strip()
    return f"{item.title}\n{summary}".strip()


def parse_verdict(text: str) -> bool | None:
    match = _ANSWER.search(text)
    if match is None:
        return None
    word = match.group(0).lower()
    if word in _YES:
        return True
    if word in _NO:
        return False
    return None


def check_sentence(
    client: Client, *, source: str, sentence: str, model: str = DEFAULT_VERIFY_MODEL
) -> Verdict:
    try:
        completion = client.generate(
            model=model,
            prompt=verify_prompt(source=source, sentence=sentence),
            system=VERIFY_SYSTEM,
            options=dict(_OPTIONS),
        )
    except OllamaError as exc:
        raise WriterError(f"the faithfulness check could not reach the model: {exc}") from exc
    answer = completion.text.strip()
    return Verdict(sentence=sentence, supported=parse_verdict(answer), answer=answer[:40])


def guard(
    judgements: Sequence[Judgement],
    items: Mapping[str, Item],
    *,
    client: Client,
    model: str = DEFAULT_VERIFY_MODEL,
) -> GuardReport:
    """Check every headline and body sentence; return the judgements as they may be shown."""
    started = time.monotonic()
    checks: dict[str, CardCheck] = {}
    for judgement in judgements:
        source = source_view(items[judgement.item_id])
        headline = check_sentence(client, source=source, sentence=judgement.headline, model=model)
        body = tuple(
            check_sentence(client, source=source, sentence=sentence, model=model)
            for sentence in split_sentences(judgement.body)
        )
        checks[judgement.item_id] = CardCheck(headline=headline, body=body)
    return assemble(
        judgements, items, checks, seconds=time.monotonic() - started, model=model
    )
