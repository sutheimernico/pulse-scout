"""The honesty validator.

The project's central claim is that Nico can believe the digest. A 7B model running on a CPU
cannot be made trustworthy by asking it nicely, so what it produces is checked mechanically
before anything is stored or shown.

What this can enforce:

* every judgement points at an item that was actually fetched,
* no item is written about twice,
* no link is invented — the card already carries the real one,
* **every number in the prose occurs in that item's own title or summary.**

The number rule is the important one. A fabricated benchmark figure or version number is the
most damaging thing a small model can produce here and the only kind of fabrication that can
be checked without a second model. Years are exempt, because "im Jahr 2026" is context rather
than a claim.

What this cannot enforce: whether the "Darum geht's dich an" sentence is *true*. A fluent,
confident, wrong relevance claim passes every check here. That risk is real, it is named in
the plan, and it belongs to the five-day verdict rather than to a regular expression.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime

from pulse_scout.models import Item, Judgement

MAX_HEADLINE_CHARS = 120
MAX_BODY_CHARS = 420
MAX_WHY_CHARS = 220

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)


class DigestRejected(RuntimeError):
    """The model produced something we will not show. The run fails; no digest is written."""


def _digits(text: str) -> set[str]:
    return {match.group(0) for match in _NUMBER.finditer(text)}


def _allowed_years(now: datetime) -> set[str]:
    """A date is context, not a claim. Everything else has to come from the source."""
    return {str(now.year), str(now.year - 1), str(now.year + 1)}


def _source_numbers(item: Item) -> set[str]:
    numbers = _digits(item.text)
    # "0.120" in the prose is honest when the source says "0.120.1"; the reverse is not, so
    # prefixes of a source number count, not extensions of it.
    for number in list(numbers):
        parts = number.replace(",", ".").split(".")
        for length in range(1, len(parts)):
            numbers.add(".".join(parts[:length]))
    return numbers


def validate_judgements(
    judgements: Sequence[Judgement],
    thread: str,
    *,
    items: Mapping[str, Item],
    now: datetime,
) -> None:
    """Raise `DigestRejected` on anything we would not stand behind. Returns None otherwise."""
    if not judgements:
        raise DigestRejected("the model returned no judgements")

    years = _allowed_years(now)
    seen: set[str] = set()

    for index, judgement in enumerate(judgements, start=1):
        where = f"judgement {index} ({judgement.item_id!r})"

        item = items.get(judgement.item_id)
        if item is None:
            raise DigestRejected(
                f"{where} refers to an item that was never fetched. "
                f"Known ids: {sorted(items)}"
            )
        if judgement.item_id in seen:
            raise DigestRejected(f"{where} writes about the same item twice")
        seen.add(judgement.item_id)

        if not judgement.headline.strip():
            raise DigestRejected(f"{where} has no headline")
        if not judgement.body.strip():
            raise DigestRejected(f"{where} has no body")
        if not judgement.why_you.strip():
            raise DigestRejected(f"{where} has no 'why this concerns you' line — that is the card")

        for field_name, value, limit in (
            ("headline", judgement.headline, MAX_HEADLINE_CHARS),
            ("body", judgement.body, MAX_BODY_CHARS),
            ("why_you", judgement.why_you, MAX_WHY_CHARS),
        ):
            if len(value) > limit:
                raise DigestRejected(
                    f"{where}: {field_name} is {len(value)} characters, over the {limit} budget"
                )

        prose = f"{judgement.headline} {judgement.body} {judgement.why_you}"
        if _URL.search(prose):
            raise DigestRejected(f"{where} contains a link; the card already carries the real one")

        allowed = _source_numbers(item) | years
        invented = _digits(prose) - allowed
        if invented:
            raise DigestRejected(
                f"{where} contains {sorted(invented)}, which do not appear in the source item "
                f"{item.title!r}"
            )

    if not thread.strip():
        raise DigestRejected("the connecting thread is empty")
    if _URL.search(thread):
        raise DigestRejected("the connecting thread contains a link")

    corpus: set[str] = set(years)
    for judgement in judgements:
        corpus |= _source_numbers(items[judgement.item_id])
    invented = _digits(thread) - corpus
    if invented:
        raise DigestRejected(f"the connecting thread contains invented numbers {sorted(invented)}")
