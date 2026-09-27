"""The faithfulness guard: what happens to a sentence the source does not support.

The honesty validator (`validate.py`) checks what can be checked by string comparison: ids,
links, numbers. The first real digest (2026-09-20) showed what it cannot check. The source said
four companies agreed to *slow* AI development; the model wrote they agreed to *stop* it.
Nothing numeric, nothing invented by id — every mechanical check passed a false sentence.

So every factual sentence the writer produces — the headline and each sentence of the body —
is put to the model a second time as a yes/no question: does this source say this? That call
lives in `llm/verifier.py`. This module is the pure half: splitting prose into sentences,
deciding what a card looks like once the verdicts are in, and scoring the guard against a
labelled set so its catch rate is a measurement rather than a hope.

The rule for a rejected sentence is to drop it, never to rephrase it. A model that got a
sentence wrong once is not asked to try again unobserved. If nothing of the body survives, the
card shows the first sentence of the source itself, verbatim and marked as such — accurate by
construction, and honest about being untranslated. A rejected headline is replaced by the
source's own title.

What this does **not** check: "Darum geht's dich an" and the "Roter Faden". Both are
interpretation rather than a report of what the source says, so "does the source support it?"
is the wrong question for them. That residual risk is F9 in the plan and stays open.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pulse_scout.core.validate import MAX_BODY_CHARS, MAX_HEADLINE_CHARS
from pulse_scout.models import Item, Judgement

# A sentence ends at . ! or ? followed by whitespace and something that starts a new sentence.
# Requiring the capital (or opening quote) keeps "v1.2" and "z. B. die" in one piece; a piece
# that ends in an abbreviation ("z. B. Die …") is glued back to what follows.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ„\"'(0-9])")
_ABBREVIATION = re.compile(
    r"(?:^|\s)(?:[A-Za-zÄÖÜäöü]|bzw|ca|Dr|Nr|vgl|inkl|etc|usw|Mio|Mrd)\.$"
)


@dataclass(frozen=True, slots=True)
class Verdict:
    """One sentence put to the checker. `supported` is None when the answer was unreadable."""

    sentence: str
    supported: bool | None
    answer: str = ""

    @property
    def keep(self) -> bool:
        # Fail closed: an answer we cannot read is not a yes.
        return self.supported is True


@dataclass(frozen=True, slots=True)
class CardCheck:
    """Everything the guard decided about one judgement."""

    headline: Verdict
    body: tuple[Verdict, ...]


@dataclass(frozen=True, slots=True)
class GuardReport:
    """The outcome of guarding one draft: the corrected judgements and what it cost."""

    judgements: list[Judgement] = field(default_factory=list)
    quoted: frozenset[str] = frozenset()
    checked: int = 0
    rejected: int = 0
    unreadable: int = 0
    seconds: float = 0.0
    model: str = ""
    # What was thrown away, kept with the digest (never shown) so a drop can be reviewed.
    dropped: tuple[dict[str, str], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "checked": self.checked,
            "rejected": self.rejected,
            "unreadable": self.unreadable,
            "seconds": round(self.seconds, 1),
            "quoted_cards": len(self.quoted),
            "dropped": list(self.dropped),
        }

    def note(self) -> str | None:
        """The line the reader sees. Silent only when every sentence held."""
        if not self.rejected:
            return None
        line = (
            f"Faktencheck: {self.rejected} von {self.checked} Sätzen verworfen, "
            f"weil die Quelle das Gesagte nicht stützt."
        )
        if self.quoted:
            line += " Wo nichts übrig blieb, steht der Originaltext der Quelle."
        return line


def split_sentences(text: str) -> list[str]:
    """German prose into sentences. Deliberately simple; the writer's output is simple too."""
    cleaned = " ".join(text.split())
    sentences: list[str] = []
    for part in _SENTENCE_END.split(cleaned):
        if not part.strip():
            continue
        if sentences and _ABBREVIATION.search(sentences[-1]):
            sentences[-1] = f"{sentences[-1]} {part.strip()}"
        else:
            sentences.append(part.strip())
    return sentences


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:—-")
    return f"{cut}…"


def source_sentence(item: Item) -> str:
    """The first sentence the source itself wrote — the fallback that cannot be unfaithful."""
    summary = item.summary.strip()
    if summary:
        first = re.split(r"(?<=[.!?])\s+", summary, maxsplit=1)[0]
        return _clip(first, MAX_BODY_CHARS)
    return _clip(item.title, MAX_BODY_CHARS)


def apply_check(judgement: Judgement, item: Item, check: CardCheck) -> tuple[Judgement, bool]:
    """The judgement as it may be shown, plus whether its body is now a verbatim quote."""
    headline = (
        judgement.headline if check.headline.keep else _clip(item.title, MAX_HEADLINE_CHARS)
    )
    kept = [verdict.sentence for verdict in check.body if verdict.keep]
    quoted = not kept
    body = source_sentence(item) if quoted else " ".join(kept)
    return (
        Judgement(
            item_id=judgement.item_id,
            headline=headline,
            body=body,
            why_you=judgement.why_you,
        ),
        quoted,
    )


def assemble(
    judgements: Sequence[Judgement],
    items: Mapping[str, Item],
    checks: Mapping[str, CardCheck],
    *,
    seconds: float,
    model: str,
) -> GuardReport:
    """Apply every card's verdicts and count what happened."""
    guarded: list[Judgement] = []
    quoted: set[str] = set()
    checked = rejected = unreadable = 0
    dropped: list[dict[str, str]] = []
    for judgement in judgements:
        check = checks[judgement.item_id]
        verdicts = (check.headline, *check.body)
        dropped += [
            {"item_id": judgement.item_id, "sentence": v.sentence, "answer": v.answer}
            for v in verdicts
            if not v.keep
        ]
        checked += len(verdicts)
        rejected += sum(1 for v in verdicts if not v.keep)
        unreadable += sum(1 for v in verdicts if v.supported is None)
        fixed, is_quote = apply_check(judgement, items[judgement.item_id], check)
        guarded.append(fixed)
        if is_quote:
            quoted.add(judgement.item_id)
    return GuardReport(
        judgements=guarded,
        quoted=frozenset(quoted),
        checked=checked,
        rejected=rejected,
        unreadable=unreadable,
        seconds=seconds,
        model=model,
        dropped=tuple(dropped),
    )


def score_labels(labels: Sequence[bool], kept: Sequence[bool]) -> dict[str, object]:
    """How good is the guard on a labelled set?

    `labels[i]` is True when a human judged sentence i faithful to its source; `kept[i]` is
    True when the guard let it through. The number that matters is the catch rate — of the
    unfaithful sentences, how many were stopped. The false-alarm rate says what that costs:
    faithful sentences thrown away.
    """
    if len(labels) != len(kept):
        raise ValueError(f"{len(labels)} labels but {len(kept)} verdicts")
    unfaithful = [k for label, k in zip(labels, kept, strict=True) if not label]
    faithful = [k for label, k in zip(labels, kept, strict=True) if label]
    caught = sum(1 for k in unfaithful if not k)
    false_alarms = sum(1 for k in faithful if not k)
    return {
        "sentences": len(labels),
        "unfaithful": len(unfaithful),
        "faithful": len(faithful),
        "caught": caught,
        "missed": len(unfaithful) - caught,
        "false_alarms": false_alarms,
        "catch_rate": round(caught / len(unfaithful), 3) if unfaithful else None,
        "false_alarm_rate": round(false_alarms / len(faithful), 3) if faithful else None,
    }
