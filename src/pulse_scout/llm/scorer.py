"""The scoring pass: a small model re-orders the forty candidates.

This step is on probation, and the code says so on purpose.

The deterministic ranking has already done the hard cut, from roughly 570 items to 40. What
the 1.5B model adds is a re-ordering of those 40 down to 12 — and a 1.5B model producing a
0–10 rating is low-resolution and order-biased. Whether that re-ordering is signal or noise is
an open question, not a settled one, and it is also the expensive half of the daily run.

So this module measures itself: it keeps the deterministic rank, the model rank and the rank
correlation between them for every run. After two weeks there will be evidence. Until then,
nothing here pretends the model pass has been shown to help.

An unparseable answer never becomes a guessed number. The candidate keeps its deterministic
rank and the run counts the failure.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from pulse_scout.core.ranking import Candidate
from pulse_scout.llm.ollama import Client, OllamaError
from pulse_scout.llm.prompts import SCORE_SYSTEM, score_prompt

DEFAULT_SCORE_MODEL = "qwen2.5:1.5b"

# Eight tokens is a number and a handful of words. Generation is the slowest thing the machine
# does, so the reason line is a bonus, not a requirement.
SCORE_OPTIONS = {"num_predict": 24, "temperature": 0.0}

_FIRST_NUMBER = re.compile(r"\b(10|[0-9])\b")


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    """A candidate with both opinions about it attached."""

    candidate: Candidate
    deterministic_rank: int
    model_score: int | None = None
    model_rank: int | None = None
    reason: str = ""
    error: str = ""

    @property
    def combined_rank(self) -> float:
        """Average of the two ranks; a candidate the model could not rate keeps its own.

        Deliberately not a weighted blend. Weighting would imply we know how much the model
        pass is worth, and that is exactly the open question.
        """
        if self.model_rank is None:
            return float(self.deterministic_rank)
        return (self.deterministic_rank + self.model_rank) / 2


@dataclass(frozen=True, slots=True)
class ScoringResult:
    scored: list[ScoredCandidate] = field(default_factory=list)
    parse_failures: int = 0
    call_failures: int = 0
    seconds: float = 0.0
    rank_correlation: float | None = None

    def finalists(self, limit: int) -> list[ScoredCandidate]:
        """The best `limit` by combined rank, ties broken deterministically."""
        return sorted(
            self.scored,
            key=lambda entry: (entry.combined_rank, entry.candidate.cluster.key),
        )[:limit]


def parse_score(text: str) -> tuple[int | None, str]:
    """Pull a 0–10 rating out of whatever the model said.

    Small models pad, apologise and explain. What they must not do is get a number invented on
    their behalf: no number means no score.
    """
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return None, ""
    match = _FIRST_NUMBER.search(lines[0])
    if match is None:
        # Some answers open with a sentence and put the rating at the end of it.
        match = _FIRST_NUMBER.search(" ".join(lines[:2]))
    if match is None:
        return None, ""
    reason = lines[1] if len(lines) > 1 else ""
    return int(match.group(1)), reason[:160]


def spearman(left: Sequence[float], right: Sequence[float]) -> float | None:
    """Rank correlation between two orderings of the same items.

    Written out rather than imported: it is six lines, and the alternative is a SciPy
    dependency for one number in a report.
    """
    if len(left) != len(right) or len(left) < 3:
        return None
    n = len(left)
    mean_left = sum(left) / n
    mean_right = sum(right) / n
    covariance = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right, strict=True))
    spread_left = sum((a - mean_left) ** 2 for a in left) ** 0.5
    spread_right = sum((b - mean_right) ** 2 for b in right) ** 0.5
    if spread_left == 0 or spread_right == 0:
        return None
    return covariance / (spread_left * spread_right)


def score_candidates(
    candidates: Sequence[Candidate],
    *,
    client: Client,
    model: str = DEFAULT_SCORE_MODEL,
) -> ScoringResult:
    """Ask the small model to rate each candidate. One short call per item."""
    scored: list[ScoredCandidate] = []
    parse_failures = 0
    call_failures = 0
    seconds = 0.0

    for position, candidate in enumerate(candidates, start=1):
        item = candidate.cluster.primary
        prompt = score_prompt(
            title=item.title, source=item.source_name, summary=item.summary
        )
        try:
            completion = client.generate(
                model=model,
                prompt=prompt,
                # A module constant, so every call shares a byte-identical prefix.
                system=SCORE_SYSTEM,
                options=SCORE_OPTIONS,
            )
        except OllamaError as exc:
            call_failures += 1
            scored.append(
                ScoredCandidate(
                    candidate=candidate, deterministic_rank=position, error=str(exc)[:200]
                )
            )
            continue

        seconds += completion.total_seconds
        value, reason = parse_score(completion.text)
        if value is None:
            parse_failures += 1
        scored.append(
            ScoredCandidate(
                candidate=candidate,
                deterministic_rank=position,
                model_score=value,
                reason=reason,
            )
        )

    scored = _assign_model_ranks(scored)
    rated = [entry for entry in scored if entry.model_rank is not None]
    correlation = spearman(
        [float(entry.deterministic_rank) for entry in rated],
        [float(entry.model_rank or 0) for entry in rated],
    )
    return ScoringResult(
        scored=scored,
        parse_failures=parse_failures,
        call_failures=call_failures,
        seconds=seconds,
        rank_correlation=correlation,
    )


def _assign_model_ranks(scored: Sequence[ScoredCandidate]) -> list[ScoredCandidate]:
    """Rank 1 is the highest model score; the deterministic rank breaks ties.

    A 1.5B model on a 0–10 scale produces a lot of ties, so the tie-break is not an edge case —
    it is most of the ordering.
    """
    rated = sorted(
        (entry for entry in scored if entry.model_score is not None),
        key=lambda entry: (-(entry.model_score or 0), entry.deterministic_rank),
    )
    ranks = {id(entry): position for position, entry in enumerate(rated, start=1)}
    return [
        ScoredCandidate(
            candidate=entry.candidate,
            deterministic_rank=entry.deterministic_rank,
            model_score=entry.model_score,
            model_rank=ranks.get(id(entry)),
            reason=entry.reason,
            error=entry.error,
        )
        for entry in scored
    ]
