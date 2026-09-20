"""Choosing what goes on the screen.

Three rules, each of which exists because of a specific failure it prevents.

**At most three of the five Pflicht slots from one tier (decision D8).** Without it, a busy AI
news day pushes Nico's own job out of his own digest — and the measured source mix makes that
likely rather than hypothetical: on 2026-09-20 the live fetch returned 22 tier 1 items against
433 tier 3 items over three days.

**Up to five, not exactly five (D-P8).** If only three finalists are worth a slot, the digest
shows three and says so. Filling a slot to reach a round number is fabrication with extra
steps, and the honesty rule is the product.

**The Kür is capped at fifteen (D-P7).** The spec says "one line per item" without saying how
many items, which after the funnel would be thirty-five lines. D1 budgets 12–20 short items in
total for five minutes. Five plus fifteen is twenty.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from pulse_scout.llm.scorer import ScoredCandidate

# How many candidates the 7B model is shown. Everything else here follows from the funnel.
FINALIST_COUNT = 12

PFLICHT_SLOTS = 5
PFLICHT_PER_TIER = 3  # D8
KUER_SLOTS = 15  # D-P7
KUER_PER_GROUP = 6

# Below this, the small model has said the item is not worth a Pflicht slot. An item the model
# could not rate is NOT excluded: a parse failure is our problem, not the item's.
MIN_MODEL_SCORE = 4

TIER_LABELS = {1: "Dein Stack", 2: "KI-Modelle", 3: "Drumherum"}


@dataclass(frozen=True, slots=True)
class Selection:
    """What the digest will show, and what had to give way."""

    pflicht: list[ScoredCandidate] = field(default_factory=list)
    kuer: list[ScoredCandidate] = field(default_factory=list)
    qualified: int = 0
    tier_capped: int = 0
    below_threshold: int = 0

    @property
    def is_quiet_day(self) -> bool:
        """Fewer than five items earned a slot. Worth saying out loud on the screen."""
        return len(self.pflicht) < PFLICHT_SLOTS

    def kuer_groups(self) -> dict[int, list[ScoredCandidate]]:
        """Kür lines grouped by tier, in tier order, each group capped."""
        groups: dict[int, list[ScoredCandidate]] = {}
        for entry in self.kuer:
            groups.setdefault(entry.candidate.tier, []).append(entry)
        return dict(sorted(groups.items()))


def _qualifies(entry: ScoredCandidate) -> bool:
    return entry.model_score is None or entry.model_score >= MIN_MODEL_SCORE


def select(
    finalists: Sequence[ScoredCandidate],
    rest: Sequence[ScoredCandidate] = (),
) -> Selection:
    """Fill the Pflicht slots from the finalists, then the Kür from everything left over.

    `finalists` must already be ordered best-first; `rest` is the remainder of the candidates,
    which never saw the model and are ranked deterministically.
    """
    pflicht: list[ScoredCandidate] = []
    per_tier: dict[int, int] = {}
    tier_capped = 0
    below_threshold = 0
    leftovers: list[ScoredCandidate] = []

    for entry in finalists:
        if len(pflicht) >= PFLICHT_SLOTS:
            leftovers.append(entry)
            continue
        if not _qualifies(entry):
            below_threshold += 1
            leftovers.append(entry)
            continue
        tier = entry.candidate.tier
        if per_tier.get(tier, 0) >= PFLICHT_PER_TIER:
            tier_capped += 1
            leftovers.append(entry)
            continue
        pflicht.append(entry)
        per_tier[tier] = per_tier.get(tier, 0) + 1

    qualified = sum(1 for entry in finalists if _qualifies(entry))

    kuer: list[ScoredCandidate] = []
    per_group: dict[int, int] = {}
    for entry in [*leftovers, *rest]:
        if len(kuer) >= KUER_SLOTS:
            break
        tier = entry.candidate.tier
        if per_group.get(tier, 0) >= KUER_PER_GROUP:
            continue
        kuer.append(entry)
        per_group[tier] = per_group.get(tier, 0) + 1

    return Selection(
        pflicht=pflicht,
        kuer=kuer,
        qualified=qualified,
        tier_capped=tier_capped,
        below_threshold=below_threshold,
    )
