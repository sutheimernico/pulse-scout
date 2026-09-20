"""Assembling the finished digest.

Everything the screen shows is fixed here, and nothing downstream computes anything — the API
reads this, the PWA renders it. That separation is deliberate: a number the interface derives
on its own is a number nobody can check against a stored run.

Two rules from the spec live in this module:

* **The funnel count is real** (`570 gesichtet → 5 für dich`). It is carried through from the
  pipeline's own counters, never estimated and never rounded up.
* **Five minutes means five minutes** (C5). The read time is computed from the finished text at
  200 words per minute plus three seconds per Kür line. Above the budget the build says so.
  An estimate that is never checked is the same as no estimate.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

from pulse_scout.core.selection import PFLICHT_SLOTS, TIER_LABELS, Selection
from pulse_scout.llm.writer import Draft
from pulse_scout.pipeline import FunnelCounters

# The reader is in Germany and reads this before work. The date on a digest is the local date
# it was produced on — never a date it was not produced on.
LOCAL_ZONE = ZoneInfo("Europe/Berlin")

WORDS_PER_MINUTE = 200
SECONDS_PER_KUER_LINE = 3
READ_BUDGET_SECONDS = 330  # five minutes, plus thirty seconds of grace before we complain


@dataclass(frozen=True, slots=True)
class Card:
    """One Pflicht card."""

    headline: str
    body: str
    why_you: str
    url: str | None
    source_name: str
    tier: int
    item_key: str


@dataclass(frozen=True, slots=True)
class KuerLine:
    """One line in the Kür — a title, so that a name has been read once."""

    title: str
    url: str | None
    source_name: str
    tier: int


@dataclass(frozen=True, slots=True)
class Digest:
    """A finished digest. Serialisable, and the only thing the API ever reads."""

    digest_date: str
    generated_at: str
    cards: list[Card] = field(default_factory=list)
    thread: str = ""
    kuer: list[KuerLine] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    read_seconds: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def funnel_line(self) -> str:
        """The header line. Real numbers, in German, as the spec requires."""
        seen = self.counters.get("items_seen", 0)
        return f"{seen} gesichtet → {len(self.cards)} für dich"

    @property
    def over_budget(self) -> bool:
        return self.read_seconds > READ_BUDGET_SECONDS

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def local_date(now: datetime) -> date:
    return now.astimezone(LOCAL_ZONE).date()


def read_seconds(cards: list[Card], thread: str, kuer: list[KuerLine]) -> int:
    """How long this actually takes to read, rounded up to the second."""
    words = sum(len(f"{c.headline} {c.body} {c.why_you}".split()) for c in cards)
    words += len(thread.split())
    prose = words / WORDS_PER_MINUTE * 60
    return int(prose + len(kuer) * SECONDS_PER_KUER_LINE + 0.999)


def build(
    *,
    selection: Selection,
    draft: Draft,
    counters: FunnelCounters,
    now: datetime,
    extra_notes: list[str] | None = None,
) -> Digest:
    """Turn a validated draft plus the selection into the object the screen renders."""
    by_key = {item.key: handle for handle, item in draft.items.items()}
    cards: list[Card] = []
    for entry in selection.pflicht:
        item = entry.candidate.cluster.primary
        handle = by_key.get(item.key)
        judgement = next(
            (j for j in draft.judgements if j.item_id == handle), None
        )
        if judgement is None:
            # The writer produced fewer judgements than there are slots. That is allowed —
            # the validator only rejects invented ones — and an unwritten slot is simply
            # not shown rather than filled with the raw headline.
            continue
        cards.append(
            Card(
                headline=judgement.headline,
                body=judgement.body,
                why_you=judgement.why_you,
                url=item.url,
                source_name=item.source_name,
                tier=entry.candidate.tier,
                item_key=item.key,
            )
        )

    kuer = [
        KuerLine(
            title=entry.candidate.cluster.primary.title,
            url=entry.candidate.cluster.primary.url,
            source_name=entry.candidate.cluster.primary.source_name,
            tier=entry.candidate.tier,
        )
        for entry in selection.kuer
    ]

    notes = list(extra_notes or [])
    if selection.is_quiet_day:
        notes.append(
            f"Ruhiger Tag: nur {len(cards)} von {PFLICHT_SLOTS} Plätzen sind belegt — "
            f"heute hat nicht mehr einen Platz verdient."
        )
    if draft.truncated:
        notes.append("Der Text wurde vom Ausgabelimit abgeschnitten.")

    seconds = read_seconds(cards, draft.thread, kuer)
    if seconds > READ_BUDGET_SECONDS:
        notes.append(f"Über dem Fünf-Minuten-Budget: {seconds // 60}:{seconds % 60:02d}.")

    return Digest(
        digest_date=local_date(now).isoformat(),
        generated_at=now.astimezone(LOCAL_ZONE).isoformat(timespec="seconds"),
        cards=cards,
        thread=draft.thread,
        kuer=kuer,
        counters=counters.as_counters(),
        read_seconds=seconds,
        notes=notes,
    )


def render_markdown(digest: Digest) -> str:
    """The digest as a file Nico can read before the PWA exists."""
    minutes, seconds = divmod(digest.read_seconds, 60)
    lines = [
        f"# pulse-scout — {digest.digest_date}",
        "",
        f"{digest.funnel_line} · {minutes}:{seconds:02d} Lesezeit · "
        f"Stand {digest.generated_at[11:16]}",
        "",
    ]
    for note in digest.notes:
        lines += [f"> {note}", ""]

    lines += ["## Heute", ""]
    if not digest.cards:
        lines += ["_Heute hat nichts einen Platz verdient._", ""]
    for card in digest.cards:
        lines += [
            f"### {card.headline}",
            "",
            card.body,
            "",
            f"**Darum geht's dich an:** {card.why_you}",
            "",
        ]
        if card.url:
            lines += [f"[{card.source_name}]({card.url})", ""]

    if digest.thread:
        lines += ["## Roter Faden", "", digest.thread, ""]

    if digest.kuer:
        lines += ["## Kür", ""]
        for tier in sorted({line.tier for line in digest.kuer}):
            lines += [f"**{TIER_LABELS.get(tier, f'Tier {tier}')}**", ""]
            for line in digest.kuer:
                if line.tier != tier:
                    continue
                label = f"[{line.title}]({line.url})" if line.url else line.title
                lines.append(f"- {label} — {line.source_name}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"
